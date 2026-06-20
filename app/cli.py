import typer
from rich.table import Table

from app.cli_ui import (
    confirm_prompt,
    console,
    print_error,
    print_field,
    print_header,
    print_menu_item,

    print_section,
    print_success,
    print_warning,
    prompt_menu_choice,
)
from app.config import settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.services.catalog_sync import sync_catalog
from app.services.client_sync import sync_clients
from app.services.panel_api import (
    PANEL_API_TOKEN_KEY,
    PANEL_WEB_BASE_PATH_KEY,
    PanelApiClient,
    PanelApiError,
    resolve_panel_token,
    resolve_panel_web_base_path,
)
from app.cli_balancer import (
    configure_balancer_interactive,
    run_balancers_menu,
)
from app.models.balancer import format_scope, format_strategy
from app.services.profile_builder import default_balancer_tag

app = typer.Typer(
    help="middlewarejson CLI — каталог инбаундов, балансировщики по группам клиентов",
    invoke_without_command=True,
)
settings_app = typer.Typer(help="Настройки Panel API")
catalog_app = typer.Typer(help="Каталог инбаундов из 3x-ui Panel API")
balancer_app = typer.Typer(help="Балансировщики и их назначение")
group_app = typer.Typer(help="Группы клиентов 3x-ui")

app.add_typer(settings_app, name="settings")
app.add_typer(catalog_app, name="catalog")
app.add_typer(balancer_app, name="balancer")
app.add_typer(group_app, name="group")

def _repo() -> CatalogRepository:
    return CatalogRepository(Database(settings.db_path))


def _mask_token(token: str) -> str:
    if not token:
        return "(not set)"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def _resolve_member_fingerprints(
    repo: CatalogRepository,
    members: list[str],
) -> list[str]:
    panel_ids: list[int] = []
    fingerprints: list[str] = []

    for member in members:
        if "|" in member:
            fingerprints.append(member)
            continue
        try:
            panel_ids.append(int(member))
        except ValueError:
            fingerprints.append(member)

    if panel_ids:
        resolved = repo.get_fingerprints_by_panel_ids(panel_ids)
        if not resolved:
            console.print(
                f"[yellow]No active catalog rows for panel IDs: {panel_ids}[/yellow]"
            )
        fingerprints.extend(resolved)

    seen: set[str] = set()
    unique: list[str] = []
    for fingerprint in fingerprints:
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(fingerprint)
    return unique


def _print_inbound_table(rows: list[dict[str, object]]) -> None:
    table = Table(title="Каталог инбаундов")
    table.add_column("#", style="dim")
    table.add_column("ID", style="cyan")
    table.add_column("Активен", style="green")
    table.add_column("Название")
    table.add_column("Протокол")
    table.add_column("Адрес:Порт")
    table.add_column("Отпечаток")

    for index, row in enumerate(rows):
        fingerprint = str(row["fingerprint"])
        short_fp = fingerprint if len(fingerprint) <= 32 else fingerprint[:29] + "..."
        panel_id = row.get("panel_inbound_id")
        address_port = f"{row['address']}:{row['port']}"
        table.add_row(
            str(index),
            str(panel_id) if panel_id is not None else "-",
            "да" if row["is_active"] else "нет",
            str(row["remarks"]),
            str(row["protocol"]),
            address_port,
            short_fp,
        )
    console.print(table)


def _do_settings_show() -> None:
    repo = _repo()
    token = resolve_panel_token(settings, repo.get_setting(PANEL_API_TOKEN_KEY))
    balancers = repo.list_balancers()
    assignments = repo.list_group_assignments()

    console.print(f"DB_PATH: {settings.db_path}")
    console.print(f"PANEL_API_BASE_URL: {settings.resolved_panel_base_url()}")
    web_path = resolve_panel_web_base_path(
        settings,
        repo.get_setting(PANEL_WEB_BASE_PATH_KEY),
    )
    console.print(f"PANEL_WEB_BASE_PATH: {web_path or '(empty)'}")
    console.print(f"PANEL_API_TOKEN: {_mask_token(token)}")
    console.print(f"balancers: {len(balancers)}")
    console.print(f"group assignments: {len(assignments)}")


def _prompt_panel_settings(repo: CatalogRepository) -> bool:
    console.print(
        "[yellow]Panel API не настроен.[/yellow] "
        "Нужны base path и API token из 3x-ui → Settings → Security."
    )
    base_path = typer.prompt(
        "Web base path панели",
        default=settings.panel_web_base_path or "",
    ).strip()
    if base_path:
        repo.set_setting(PANEL_WEB_BASE_PATH_KEY, base_path)

    token = typer.prompt("API token", hide_input=True).strip()
    if not token:
        console.print("[red]Token обязателен[/red]")
        return False

    repo.set_setting(PANEL_API_TOKEN_KEY, token)
    console.print("[green]Panel API token сохранён[/green]")
    return True


def _ensure_panel_token(repo: CatalogRepository, *, prompt: bool = True) -> str | None:
    token = resolve_panel_token(settings, repo.get_setting(PANEL_API_TOKEN_KEY))
    if token:
        return token
    if not prompt:
        return None
    if _prompt_panel_settings(repo):
        return resolve_panel_token(settings, repo.get_setting(PANEL_API_TOKEN_KEY))
    return None


def _do_settings_set(
    panel_token: str | None = None,
    panel_base_path: str | None = None,
) -> None:
    repo = _repo()
    if panel_token:
        repo.set_setting(PANEL_API_TOKEN_KEY, panel_token.strip())
        console.print("[green]Panel API token сохранён[/green]")
    if panel_base_path is not None:
        repo.set_setting(PANEL_WEB_BASE_PATH_KEY, panel_base_path.strip())
        console.print(f"[green]panel_web_base_path = {panel_base_path.strip()}[/green]")


def _do_panel_test() -> None:
    repo = _repo()
    token = _ensure_panel_token(repo)
    if not token:
        return

    web_path = resolve_panel_web_base_path(
        settings,
        repo.get_setting(PANEL_WEB_BASE_PATH_KEY),
    )
    result = PanelApiClient(settings, token, web_base_path=web_path).probe_connection()

    console.print()
    print_field("Запрос", f"{result.method} {result.url}")
    print_field("Ответ", result.summary)
    print_field("Время", f"{result.elapsed_ms:.0f} мс")

    if result.ok:
        print_success(f"Подключение OK — {result.inbound_count} инбаундов")
    else:
        print_error(result.error or "Подключение не удалось")


def _do_catalog_sync() -> None:
    repo = _repo()
    if not _ensure_panel_token(repo):
        return

    try:
        result = sync_catalog(settings, repo)
    except Exception as exc:
        console.print(f"[red]sync failed: {exc}[/red]")
        return

    console.print(
        f"[green]Synced {result['total_active']} endpoints "
        f"from {result['panel_inbounds']} panel inbounds "
        f"(upserted={result['upserted']}, deactivated={result['deactivated']})[/green]"
    )


def _do_catalog_list(active_only: bool = False) -> list[dict[str, object]]:
    repo = _repo()
    rows = repo.list_inbounds(active_only=active_only)
    if not rows:
        console.print("[yellow]Catalog is empty. Use: catalog sync[/yellow]")
        return []
    _print_inbound_table(rows)
    return rows


def _do_group_sync() -> None:
    repo = _repo()
    if not _ensure_panel_token(repo):
        return

    try:
        result = sync_clients(settings, repo)
    except Exception as exc:
        console.print(f"[red]sync failed: {exc}[/red]")
        return

    console.print(
        f"[green]Synced {result['upserted']} clients "
        f"({result['groups']} groups, removed={result['removed']})[/green]"
    )


def _do_group_list() -> None:
    repo = _repo()
    groups = repo.list_groups()

    if not groups:
        print_warning("Групп нет. Выполните синхронизацию (п. 6 в меню).")
        return

    table = Table(title="Группы клиентов")
    table.add_column("Группа")
    table.add_column("Клиентов", justify="right")
    table.add_column("Балансировщики")

    for group_name in groups:
        clients = repo.list_clients_by_group(group_name)
        balancers = repo.list_balancers_for_group(group_name)
        balancer_label = ", ".join(balancers) if balancers else "—"
        table.add_row(group_name, str(len(clients)), balancer_label)

    console.print(table)


def _do_group_assign(group_name: str, balancer_tag: str) -> None:
    repo = _repo()
    try:
        repo.assign_group_balancer(group_name.strip(), balancer_tag.strip())
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    console.print(
        f"[green]Группа '{group_name.strip()}' → балансировщик '{balancer_tag.strip()}'[/green]"
    )


def _do_group_unassign(group_name: str) -> None:
    repo = _repo()
    if repo.unassign_group_balancer(group_name.strip()):
        console.print(f"[green]Привязка снята для группы '{group_name.strip()}'[/green]")
    else:
        console.print(f"[yellow]Группа '{group_name.strip()}' не была привязана[/yellow]")


def _do_group_show(group_name: str) -> None:
    repo = _repo()
    clients = repo.list_clients_by_group(group_name.strip())
    if not clients:
        console.print(f"[yellow]Клиентов в группе '{group_name.strip()}' нет[/yellow]")
        return

    balancers = repo.list_balancers_for_group(group_name.strip())
    balancer_label = ", ".join(balancers) if balancers else "—"
    console.print(f"[bold]{group_name.strip()}[/bold] — балансировщики: {balancer_label}")
    for client in clients:
        status = "on" if client.enable else "off"
        console.print(f"  {client.email or '(no email)'}  sub_id={client.sub_id}  [{status}]")


def _do_balancers_menu() -> None:
    run_balancers_menu(
        _repo(),
        list_inbounds=_do_catalog_list,
        resolve_member_fingerprints=_resolve_member_fingerprints,
    )


def _print_balancer_list_only() -> None:
    from app.cli_balancer import print_balancer_table

    repo = _repo()
    balancers = repo.list_balancers()
    if not balancers:
        console.print("[yellow]Балансировщиков нет[/yellow]")
        return
    print_balancer_table(balancers)


def _do_sync_all() -> None:
    repo = _repo()
    if not _ensure_panel_token(repo):
        return

    console.print("[bold]Синхронизация каталога инбаундов…[/bold]")
    try:
        catalog_result = sync_catalog(settings, repo)
    except Exception as exc:
        print_error(f"Синхронизация каталога не удалась: {exc}")
        return

    print_success(
        f"Каталог: {catalog_result['total_active']} эндпоинтов "
        f"из {catalog_result['panel_inbounds']} инбаундов панели "
        f"(обновлено={catalog_result['upserted']}, "
        f"деактивировано={catalog_result['deactivated']})"
    )

    console.print()
    console.print("[bold]Синхронизация клиентов и групп…[/bold]")
    try:
        clients_result = sync_clients(settings, repo)
    except Exception as exc:
        print_error(f"Синхронизация клиентов не удалась: {exc}")
        return

    print_success(
        f"Клиенты: {clients_result['upserted']} записей "
        f"({clients_result['groups']} групп, удалено={clients_result['removed']})"
    )


_MENU_HELP = frozenset({"?", "help", "h", "меню", "m"})


def _print_interactive_menu() -> None:
    print_section("Настройки")
    print_menu_item(1, "Показать настройки панели")
    print_menu_item(2, "Проверить подключение к панели")

    print_section("Данные панели")
    print_menu_item(3, "Список инбаундов")
    print_menu_item(4, "Список групп")

    print_section("Балансировщики")
    print_menu_item(5, "Балансировщики")

    print_section("Синхронизация")
    print_menu_item(6, "Синхронизация")

    console.print()
    print_menu_item(0, "Выход")


def run_interactive_menu() -> None:
    print_header(
        "middlewarejson",
        subtitle="трансформация JSON-подписок 3x-ui",
    )
    _print_interactive_menu()

    while True:
        choice = prompt_menu_choice()

        if choice in _MENU_HELP:
            _print_interactive_menu()
            continue
        if not choice:
            print_warning("Введите номер: 1-6, 0 — выход, ? — полное меню")
            continue

        if choice == "0":
            console.print("[dim]До свидания[/dim]")
            break
        if choice == "1":
            _do_settings_show()
            if confirm_prompt("Изменить API token панели?", default=False):
                token = typer.prompt("API token", hide_input=True).strip()
                if token:
                    _repo().set_setting(PANEL_API_TOKEN_KEY, token)
                    print_success("Token сохранён")
        elif choice == "2":
            _do_panel_test()
        elif choice == "3":
            _do_catalog_list(active_only=False)
        elif choice == "4":
            _do_group_list()
        elif choice == "5":
            _do_balancers_menu()
        elif choice == "6":
            _do_sync_all()
        else:
            print_warning("Неизвестный пункт")


@app.callback()
def main_entry(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        run_interactive_menu()


@settings_app.command("set")
def settings_set(
    panel_token: str = typer.Option("", "--panel-token"),
    panel_base_path: str = typer.Option("", "--panel-base-path"),
) -> None:
    """Сохранить настройки Panel API в SQLite."""
    if not panel_token and not panel_base_path:
        console.print("[red]Укажите --panel-token и/или --panel-base-path[/red]")
        raise typer.Exit(1)
    _do_settings_set(
        panel_token=panel_token or None,
        panel_base_path=panel_base_path or None,
    )


@settings_app.command("show")
def settings_show() -> None:
    _do_settings_show()


@settings_app.command("test")
def settings_test() -> None:
    """Проверить подключение к Panel API."""
    _do_panel_test()


@catalog_app.command("sync")
def catalog_sync_cmd() -> None:
    """Обновить каталог инбаундов из Panel API."""
    _do_catalog_sync()


@catalog_app.command("list")
def catalog_list(
    active_only: bool = typer.Option(False, "--active-only"),
) -> None:
    _do_catalog_list(active_only=active_only)


@group_app.command("sync")
def group_sync_cmd() -> None:
    """Синхронизировать client_index из Panel API."""
    _do_group_sync()


@group_app.command("list")
def group_list_cmd() -> None:
    _do_group_list()


@group_app.command("assign")
def group_assign_cmd(
    group: str = typer.Option(..., "--group"),
    balancer: str = typer.Option(..., "--balancer"),
) -> None:
    _do_group_assign(group, balancer)


@group_app.command("unassign")
def group_unassign_cmd(
    group: str = typer.Option(..., "--group"),
) -> None:
    _do_group_unassign(group)


@group_app.command("show")
def group_show_cmd(
    group: str = typer.Option(..., "--group"),
) -> None:
    _do_group_show(group)


@balancer_app.command("create")
def balancer_create(
    name: str = typer.Option(..., "--name", help="Отображаемое имя профиля в HAPP"),
    members: str = typer.Option(
        ...,
        "--members",
        help="panel_inbound_id (3,5,7) или fingerprints через запятую",
    ),
    tag: str = typer.Option("", "--tag", help="Тег балансировщика (по умолчанию из name)"),
    strategy: str = typer.Option("roundRobin", "--strategy"),
    scope: str = typer.Option("disabled", "--scope", help="disabled|group|all|client"),
    scope_target: str = typer.Option("", "--scope-target", help="group name или sub_id"),
) -> None:
    repo = _repo()
    raw_members = [part.strip() for part in members.split(",") if part.strip()]
    fingerprints = _resolve_member_fingerprints(repo, raw_members)
    if not fingerprints:
        console.print("[red]--members must resolve to at least one fingerprint[/red]")
        raise typer.Exit(1)

    balancer_tag = tag or default_balancer_tag(name)
    repo.create_balancer(
        tag=balancer_tag,
        remarks=name,
        strategy=strategy,
        member_fingerprints=fingerprints,
        scope=scope,
        scope_target=scope_target,
    )
    print_success(
        f"Балансировщик «{balancer_tag}» создан — "
        f"{format_scope(scope, scope_target)}, {format_strategy(strategy)}"
    )


@balancer_app.command("list")
def balancer_list_cmd() -> None:
    _print_balancer_list_only()


@balancer_app.command("configure")
def balancer_configure_cmd(
    tag: str = typer.Option(..., "--tag"),
) -> None:
    """Настроить балансировщик: scope, strategy, members."""
    configure_balancer_interactive(
        _repo(),
        tag,
        list_inbounds=_do_catalog_list,
        resolve_member_fingerprints=_resolve_member_fingerprints,
    )


@balancer_app.command("set-scope")
def balancer_set_scope_cmd(
    tag: str = typer.Option(..., "--tag"),
    scope: str = typer.Option(..., "--scope"),
    target: str = typer.Option("", "--target"),
) -> None:
    repo = _repo()
    if not repo.set_balancer_scope(tag, scope, target):
        console.print(f"[red]Балансировщик '{tag}' не найден[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{tag} → {format_scope(scope, target)}[/green]")


@balancer_app.command("delete")
def balancer_delete(
    tag: str = typer.Option(..., "--tag"),
) -> None:
    repo = _repo()
    if repo.delete_balancer(tag):
        console.print(f"[green]Удалён балансировщик '{tag}'[/green]")
    else:
        console.print(f"[red]Балансировщик '{tag}' не найден[/red]")
        raise typer.Exit(1)


@app.command("interactive")
def interactive_cmd() -> None:
    """Интерактивное меню."""
    run_interactive_menu()


def main() -> None:
    app()


if __name__ == "__main__":
    main()