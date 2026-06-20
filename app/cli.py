import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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
from app.services.profile_builder import default_balancer_tag

app = typer.Typer(
    help="middlewarejson CLI — каталог инбаундов, балансировщики по группам клиентов",
    invoke_without_command=True,
)
settings_app = typer.Typer(help="Настройки Panel API")
catalog_app = typer.Typer(help="Каталог инбаундов из 3x-ui Panel API")
balancer_app = typer.Typer(help="Балансировщики (привязка к группам через group assign)")
group_app = typer.Typer(help="Группы клиентов 3x-ui")

app.add_typer(settings_app, name="settings")
app.add_typer(catalog_app, name="catalog")
app.add_typer(balancer_app, name="balancer")
app.add_typer(group_app, name="group")

console = Console()


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
    table = Table(title="Inbound catalog")
    table.add_column("#", style="dim")
    table.add_column("ID", style="cyan")
    table.add_column("Active", style="green")
    table.add_column("Remark")
    table.add_column("Proto")
    table.add_column("Address:Port")
    table.add_column("Fingerprint")

    for index, row in enumerate(rows):
        fingerprint = str(row["fingerprint"])
        short_fp = fingerprint if len(fingerprint) <= 32 else fingerprint[:29] + "..."
        panel_id = row.get("panel_inbound_id")
        address_port = f"{row['address']}:{row['port']}"
        table.add_row(
            str(index),
            str(panel_id) if panel_id is not None else "-",
            "yes" if row["is_active"] else "no",
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
    try:
        count = PanelApiClient(settings, token, web_base_path=web_path).test_connection()
    except PanelApiError as exc:
        console.print(f"[red]Panel API error: {exc}[/red]")
        return

    console.print(f"[green]Panel API OK: {count} inbounds[/green]")


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
    assignments = {item.group_name: item for item in repo.list_group_assignments()}

    if not groups:
        console.print("[yellow]Групп нет. Запустите: group sync[/yellow]")
        return

    table = Table(title="Client groups")
    table.add_column("Group")
    table.add_column("Clients", justify="right")
    table.add_column("Balancer")

    for group_name in groups:
        clients = repo.list_clients_by_group(group_name)
        assignment = assignments.get(group_name)
        balancer = assignment.balancer_tag if assignment else "(none)"
        table.add_row(group_name, str(len(clients)), balancer)

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

    balancer = repo.get_balancer_for_group(group_name.strip())
    console.print(f"[bold]{group_name.strip()}[/bold] — balancer: {balancer or '(none)'}")
    for client in clients:
        status = "on" if client.enable else "off"
        console.print(f"  {client.email or '(no email)'}  sub_id={client.sub_id}  [{status}]")


def _do_balancer_create_interactive() -> None:
    rows = _do_catalog_list(active_only=True)
    if not rows:
        return

    selection = typer.prompt("Номера строк из таблицы выше (например 0,6,9)")
    try:
        indices = [int(part.strip()) for part in selection.split(",") if part.strip()]
        fingerprints = [str(rows[i]["fingerprint"]) for i in indices]
    except (ValueError, IndexError):
        console.print("[red]Неверные индексы[/red]")
        return

    name = typer.prompt("Имя балансировщика (для HAPP)", default="Balance")
    tag = default_balancer_tag(name)

    _repo().create_balancer(
        tag=tag,
        remarks=name.strip(),
        strategy="roundRobin",
        member_fingerprints=fingerprints,
    )
    console.print(f"[green]Балансировщик '{tag}' создан[/green]")


def _do_balancer_list() -> None:
    repo = _repo()
    balancers = repo.list_balancers()
    if not balancers:
        console.print("[yellow]Балансировщиков нет[/yellow]")
        return

    catalog_by_fp = {
        str(row["fingerprint"]): row for row in repo.list_inbounds(active_only=False)
    }

    for balancer in balancers:
        console.print(f"\n[bold]{balancer.tag}[/bold] — {balancer.remarks} ({balancer.strategy})")
        for fingerprint in balancer.member_fingerprints:
            row = catalog_by_fp.get(fingerprint)
            if row and row.get("panel_inbound_id") is not None:
                panel_info = f"id={row['panel_inbound_id']} ep={row.get('endpoint_index', 0)}"
            else:
                panel_info = "id=?"
            console.print(f"  [{panel_info}] {fingerprint}")


def _do_balancer_delete_interactive() -> None:
    tag = typer.prompt("Тег балансировщика")
    if _repo().delete_balancer(tag.strip()):
        console.print(f"[green]Удалён балансировщик '{tag.strip()}'[/green]")
    else:
        console.print(f"[red]Балансировщик '{tag.strip()}' не найден[/red]")


def _do_group_assign_interactive() -> None:
    _do_group_sync()
    _do_group_list()
    groups = _repo().list_groups()
    if not groups:
        return

    group_name = typer.prompt("Имя группы")
    balancers = _repo().list_balancers()
    if not balancers:
        console.print("[red]Сначала создайте балансировщик[/red]")
        return

    for balancer in balancers:
        console.print(f"  - {balancer.tag} ({balancer.remarks})")
    balancer_tag = typer.prompt("Тег балансировщика")
    _do_group_assign(group_name, balancer_tag)


def run_interactive_menu() -> None:
    console.print(
        Panel.fit(
            "[bold]middlewarejson[/bold] — балансировщики по группам клиентов 3x-ui",
            border_style="cyan",
        )
    )

    while True:
        console.print()
        console.print("[bold]Меню[/bold]")
        console.print("  1. Настройки")
        console.print("  2. Проверить Panel API")
        console.print("  3. Синхронизировать каталог (catalog sync)")
        console.print("  4. Список инбаундов")
        console.print("  5. Синхронизировать клиентов (group sync)")
        console.print("  6. Список групп")
        console.print("  7. Создать балансировщик")
        console.print("  8. Список балансировщиков")
        console.print("  9. Назначить балансировщик группе")
        console.print(" 10. Удалить балансировщик")
        console.print("  0. Выход")

        choice = typer.prompt("Выбор", default="0").strip()

        if choice == "0":
            console.print("[dim]Bye[/dim]")
            break
        if choice == "1":
            _do_settings_show()
            if typer.confirm("Изменить Panel API token?", default=False):
                token = typer.prompt("API token", hide_input=True).strip()
                if token:
                    _repo().set_setting(PANEL_API_TOKEN_KEY, token)
                    console.print("[green]Token сохранён[/green]")
        elif choice == "2":
            _do_panel_test()
        elif choice == "3":
            _do_catalog_sync()
        elif choice == "4":
            _do_catalog_list(active_only=False)
        elif choice == "5":
            _do_group_sync()
        elif choice == "6":
            _do_group_list()
        elif choice == "7":
            _do_balancer_create_interactive()
        elif choice == "8":
            _do_balancer_list()
        elif choice == "9":
            _do_group_assign_interactive()
        elif choice == "10":
            _do_balancer_delete_interactive()
        else:
            console.print("[yellow]Неизвестный пункт[/yellow]")


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
    )
    console.print(f"[green]Балансировщик '{balancer_tag}' создан ({len(fingerprints)} members)[/green]")


@balancer_app.command("list")
def balancer_list_cmd() -> None:
    _do_balancer_list()


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