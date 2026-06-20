import re

import typer
from rich import box
from rich.table import Table

from app.cli_ui import (
    CANCEL_HINT,
    confirm_prompt,
    console,
    print_error,
    print_field,
    print_header,
    print_info,
    print_menu_item,
    print_section,
    print_success,
    print_warning,
    prompt_line,
)
from app.config import settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.services.catalog_sync import sync_catalog
from app.services.client_sync import sync_clients
from app.services.panel_api import (
    PANEL_API_BASE_URL_KEY,
    PANEL_API_TOKEN_KEY,
    PANEL_WEB_BASE_PATH_KEY,
    PanelApiClient,
    PanelApiError,
    resolve_panel_base_url,
    resolve_panel_token,
    resolve_panel_web_base_path,
    resolve_upstream_base_url,
)
from app.cli_balancer import (
    configure_balancer_interactive,
    run_balancers_menu,
)
from app.cli_service import run_install_systemd, run_service_status_menu
from app.models.balancer import format_scope, format_strategy
from app.country_flags import apply_flag_prefix
from app.services.profile_builder import default_balancer_tag

app = typer.Typer(
    help="middlewarejson CLI — каталог инбаундов, балансировщики по группам клиентов",
    invoke_without_command=True,
)
settings_app = typer.Typer(help="Настройки Panel API")
catalog_app = typer.Typer(help="Каталог инбаундов из 3x-ui Panel API")
balancer_app = typer.Typer(help="Балансировщики и их назначение")
group_app = typer.Typer(help="Группы клиентов 3x-ui")
service_app = typer.Typer(help="Systemd-служба агента")

app.add_typer(settings_app, name="settings")
app.add_typer(service_app, name="service")
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


def _display_remarks(value: str, *, max_len: int = 20) -> str:
    cleaned = re.sub(r"[\U0001F1E6-\U0001F1FF]{2}\s*", "", value).strip()
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1] + "…"
    return cleaned


def _format_endpoint(row: dict[str, object]) -> str:
    address = str(row.get("address") or "").strip()
    port = int(row.get("port") or 0)
    if address and port:
        return f"{address}:{port}"
    if address:
        return address
    if port:
        return f"порт {port}"
    return "—"


def _print_inbound_table(
    rows: list[dict[str, object]],
    *,
    for_selection: bool = False,
) -> None:
    active_count = sum(1 for row in rows if row["is_active"])
    table = Table(
        title="Каталог инбаундов",
        box=box.SIMPLE_HEAD,
        show_footer=True,
        footer_style="dim",
        pad_edge=False,
    )
    table.add_column("#", style="bold", width=3, justify="right")
    table.add_column("ID", style="cyan", width=4, justify="right")
    table.add_column("Статус", width=6, no_wrap=True)
    table.add_column("Название", width=20, overflow="ellipsis", no_wrap=True)
    table.add_column("Прот.", width=8, overflow="ellipsis", no_wrap=True)
    table.add_column("Эндпоинт", width=32, overflow="ellipsis", no_wrap=True)
    table.add_column("Сеть", width=8, overflow="ellipsis", no_wrap=True)

    for index, row in enumerate(rows):
        panel_id = row.get("panel_inbound_id")
        network = str(row.get("network") or "—")
        is_active = bool(row["is_active"])
        status = "[green]вкл[/green]" if is_active else "[dim]выкл[/dim]"
        table.add_row(
            str(index),
            str(panel_id) if panel_id is not None else "—",
            status,
            _display_remarks(str(row["remarks"])),
            str(row["protocol"]),
            _format_endpoint(row),
            network,
        )

    table.columns[0].footer = ""
    table.columns[1].footer = ""
    table.columns[2].footer = ""
    table.columns[3].footer = f"всего {len(rows)}"
    table.columns[4].footer = ""
    table.columns[5].footer = f"активных {active_count}"
    table.columns[6].footer = ""
    console.print(table)
    if for_selection:
        print_info(
            f"Выбирайте номера из колонки # (0, 1, 2…), не ID из панели. {CANCEL_HINT}"
        )


def _resolved_panel_settings(repo: CatalogRepository) -> tuple[str, str, str]:
    base_url = resolve_panel_base_url(
        settings,
        repo.get_setting(PANEL_API_BASE_URL_KEY),
    )
    web_path = resolve_panel_web_base_path(
        settings,
        repo.get_setting(PANEL_WEB_BASE_PATH_KEY),
    )
    token = resolve_panel_token(settings, repo.get_setting(PANEL_API_TOKEN_KEY))
    return base_url, web_path, token


def _print_env_override_hints() -> None:
    if settings.panel_api_base_url:
        print_warning("URL панели задан в .env — имеет приоритет над базой")
    if settings.panel_web_base_path:
        print_warning("Web base path задан в .env — имеет приоритет над базой")
    if settings.panel_api_token:
        print_warning("API token задан в .env — имеет приоритет над базой")


def _do_panel_settings_show() -> None:
    repo = _repo()
    base_url, web_path, token = _resolved_panel_settings(repo)
    balancers = repo.list_balancers()
    assignments = repo.list_group_assignments()

    console.print()
    print_field("URL панели", base_url or "—")
    print_field("Web base path", web_path or "—")
    print_field("API token", _mask_token(token))
    print_field("Балансировщиков", str(len(balancers)))
    print_field("Привязок к группам", str(len(assignments)))
    _print_env_override_hints()


def _do_script_settings_show() -> None:
    repo = _repo()
    balancers = repo.list_balancers()
    upstream_base = resolve_upstream_base_url(
        settings,
        repo.get_setting(PANEL_API_BASE_URL_KEY),
    )
    upstream_path = settings.upstream_json_path.rstrip("/")
    mode = settings.transform_mode.strip().lower()

    console.print()
    print_field("Агент", f"{settings.agent_host}:{settings.agent_port}")
    agent_path = settings.resolved_agent_json_path()
    print_field("URL агента", f"http://{settings.agent_host}:{settings.agent_port}")
    print_field("Путь подписки (агент)", f"{agent_path}/<sub_id>")
    print_field("Режим трансформации", settings.transform_mode)
    print_field("База данных", settings.db_path)
    print_field("Upstream", f"{upstream_base}{upstream_path}/<sub_id>")
    startup_sync = "да" if settings.panel_sync_on_startup else "нет"
    interval = settings.panel_sync_interval.strip() or "выкл"
    print_field("Синхр. при старте", startup_sync)
    print_field("Синхр. интервал", interval)
    print_info("Параметры скрипта задаются в .env — после изменений перезапустите службу")
    if balancers and mode != "rules":
        print_warning(
            "Балансировщики не применяются в подписке. "
            "Установите TRANSFORM_MODE=rules в .env и перезапустите сервер."
        )


def _do_settings_show() -> None:
    _do_panel_settings_show()


def _do_edit_panel_settings(repo: CatalogRepository) -> None:
    while True:
        base_url, web_path, token = _resolved_panel_settings(repo)
        console.print()
        print_field("URL панели", base_url or "—")
        print_field("Web base path", web_path or "—")
        print_field("API token", _mask_token(token))
        _print_env_override_hints()

        console.print()
        print_menu_item(1, "Изменить URL панели")
        print_menu_item(2, "Изменить web base path")
        print_menu_item(3, "Изменить API token")
        print_menu_item(0, "Назад")

        choice = prompt_line("Выбор [0 — назад]")
        if choice == "0" or not choice:
            return

        if choice == "1":
            if settings.panel_api_base_url:
                print_warning("Сначала уберите PANEL_API_BASE_URL из .env")
                continue
            new_url = typer.prompt("URL панели", default=base_url).strip()
            if new_url:
                repo.set_setting(PANEL_API_BASE_URL_KEY, new_url)
                print_success("URL панели сохранён")
        elif choice == "2":
            if settings.panel_web_base_path:
                print_warning("Сначала уберите PANEL_WEB_BASE_PATH из .env")
                continue
            new_path = typer.prompt(
                "Web base path панели",
                default=web_path,
            ).strip()
            repo.set_setting(PANEL_WEB_BASE_PATH_KEY, new_path)
            print_success("Web base path сохранён")
        elif choice == "3":
            if settings.panel_api_token:
                print_warning("Сначала уберите PANEL_API_TOKEN из .env")
                continue
            new_token = typer.prompt("API token", hide_input=True).strip()
            if new_token:
                repo.set_setting(PANEL_API_TOKEN_KEY, new_token)
                print_success("API token сохранён")
        else:
            print_warning("Неизвестный пункт")


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

    base_url, web_path, _ = _resolved_panel_settings(repo)
    result = PanelApiClient(
        settings,
        token,
        web_base_path=web_path,
        api_base_url=base_url,
    ).probe_connection()

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


def _do_catalog_list(
    active_only: bool = False,
    *,
    for_selection: bool = False,
) -> list[dict[str, object]]:
    repo = _repo()
    rows = repo.list_inbounds(active_only=active_only)
    if not rows:
        print_warning("Каталог пуст. Выполните синхронизацию (п. 6 в меню).")
        return []
    _print_inbound_table(rows, for_selection=for_selection)
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

    print_success(
        f"Клиенты: {result['upserted']} "
        f"(групп в панели {result['groups']}, "
        f"с клиентами {result['groups_with_clients']}, "
        f"удалено={result['removed']})"
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
        f"Клиенты: {clients_result['upserted']} "
        f"(групп в панели {clients_result['groups']}, "
        f"с клиентами {clients_result['groups_with_clients']}, "
        f"удалено={clients_result['removed']})"
    )


def _do_run_server() -> None:
    host = settings.agent_host
    port = settings.agent_port
    print_info(f"Запуск на http://{host}:{port} — Ctrl+C для остановки")
    try:
        import uvicorn

        uvicorn.run("app.main:app", host=host, port=port, log_level="info")
    except KeyboardInterrupt:
        console.print()
        print_info("Сервер остановлен")
    except OSError as exc:
        print_error(f"Не удалось запустить сервер: {exc}")


def _print_interactive_menu() -> None:
    print_section("Настройки")
    print_menu_item(1, "Показать настройки панели")
    print_menu_item(2, "Показать настройки скрипта")
    print_menu_item(3, "Проверить подключение к панели")
    print_menu_item(4, "Проверить состояние скрипта (systemd)")
    print_menu_item(5, "Установить службу systemd")

    print_section("Данные панели")
    print_menu_item(6, "Список инбаундов")
    print_menu_item(7, "Список групп")

    print_section("Настройка JSON")
    print_menu_item(8, "Балансировщики")

    print_section("Синхронизация")
    print_menu_item(9, "Синхронизация")

    print_section("Отладка")
    print_menu_item(10, f"Запустить агент вручную (uvicorn :{settings.agent_port})")

    console.print()
    print_menu_item(0, "Выход")


def run_interactive_menu() -> None:
    print_header(
        "middlewarejson",
        subtitle="трансформация JSON-подписок 3x-ui",
    )

    while True:
        _print_interactive_menu()
        choice = typer.prompt("Выбор", default="0").strip()

        if choice == "0":
            console.print("[dim]До свидания[/dim]")
            break
        if choice == "1":
            _do_panel_settings_show()
            if confirm_prompt("Изменить настройки панели?", default=False):
                _do_edit_panel_settings(_repo())
        elif choice == "2":
            _do_script_settings_show()
        elif choice == "3":
            _do_panel_test()
        elif choice == "4":
            run_service_status_menu()
        elif choice == "5":
            run_install_systemd()
        elif choice == "6":
            _do_catalog_list(active_only=False)
        elif choice == "7":
            _do_group_list()
        elif choice == "8":
            _do_balancers_menu()
        elif choice == "9":
            _do_sync_all()
        elif choice == "10":
            _do_run_server()
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
    _do_panel_settings_show()


@settings_app.command("script-show")
def settings_script_show() -> None:
    """Показать настройки скрипта (агент, transform, upstream, sync)."""
    _do_script_settings_show()


@settings_app.command("test")
def settings_test() -> None:
    """Проверить подключение к Panel API."""
    _do_panel_test()


@service_app.command("status")
def service_status_cmd() -> None:
    """Состояние systemd-службы и меню управления."""
    run_service_status_menu()


@service_app.command("install")
def service_install_cmd() -> None:
    """Установить unit-файл middlewarejson в systemd."""
    run_install_systemd()


@service_app.command("start")
def service_start_cmd() -> None:
    """Запустить службу middlewarejson."""
    from app.services.systemd_service import start_service

    ok, message = start_service()
    if ok:
        print_success(message)
    else:
        print_error(message)
        raise typer.Exit(1)


@service_app.command("restart")
def service_restart_cmd() -> None:
    """Перезапустить службу middlewarejson."""
    from app.services.systemd_service import restart_service

    ok, message = restart_service()
    if ok:
        print_success(message)
    else:
        print_error(message)
        raise typer.Exit(1)


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
    flag: str = typer.Option(
        "",
        "--flag",
        help="Код страны для иконки в HAPP (nl, us, de…)",
    ),
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

    remarks = apply_flag_prefix(name, flag or None)
    balancer_tag = tag or default_balancer_tag(remarks)
    repo.create_balancer(
        tag=balancer_tag,
        remarks=remarks,
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