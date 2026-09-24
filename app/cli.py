import typer

from app.cli_ops import (
    preview_subscription,
    print_dashboard,
    print_status_bar,
    run_preview_interactive,
    run_service_menu,
)
from app.cli_service import run_install_systemd, run_service_status_menu
from app.cli_ui import (
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
    text_prompt,
)
from app.config import settings
from app.db.database import Database
from app.db.repository import SettingsRepository
from app.services.mode import (
    TRANSFORM_MODE_KEY,
    normalize_transform_mode,
    resolve_transform_mode,
)

app = typer.Typer(
    help="middlewarejson CLI — прослойка JSON-подписок 3x-ui для iOS/HAPP",
    invoke_without_command=True,
)
settings_app = typer.Typer(help="Настройки агента и режима")
service_app = typer.Typer(help="Systemd-служба агента")

app.add_typer(settings_app, name="settings")
app.add_typer(service_app, name="service")


def _repo() -> SettingsRepository:
    return SettingsRepository(Database(settings.db_path))


def _transform_mode_label(mode: str) -> str:
    if mode == "ios-fix-beta":
        return "ios-fix-beta — ios-fix + блок QUIC (UDP 443) + DNS в прокси"
    if mode == "ios-fix":
        return "ios-fix — mixed→socks, балансер 3x-ui под iOS"
    return "passthrough — подписка без изменений"


def _resolved_transform_mode(repo: SettingsRepository) -> str:
    return resolve_transform_mode(settings, repo.get_setting(TRANSFORM_MODE_KEY))


def _do_set_transform_mode(mode: str) -> None:
    repo = _repo()
    normalized = normalize_transform_mode(mode)
    repo.set_setting(TRANSFORM_MODE_KEY, normalized)
    print_success(f"Режим трансформации: {_transform_mode_label(normalized)}")
    print_info("Действует сразу для запросов подписки (перезапуск не обязателен)")


def _do_edit_transform_mode(repo: SettingsRepository) -> None:
    current = _resolved_transform_mode(repo)
    console.print()
    print_field("Текущий режим", _transform_mode_label(current))
    print_menu_item(1, "ios-fix — socks вместо mixed, leastPing/leastLoad/roundRobin под iOS")
    print_menu_item(2, "ios-fix-beta — ios-fix + блок QUIC (UDP 443) + DNS в прокси")
    print_menu_item(3, "passthrough — подписка без изменений")
    print_menu_item(0, "Назад")

    choice = prompt_line("Выбор [0 — назад]")
    if choice == "0" or not choice:
        return
    if choice == "1":
        target = "ios-fix"
    elif choice == "2":
        target = "ios-fix-beta"
    elif choice == "3":
        target = "passthrough"
    else:
        print_warning("Неизвестный пункт")
        return

    if target == current:
        print_info("Режим уже выбран")
        return
    _do_set_transform_mode(target)


def _do_script_settings_show() -> None:
    repo = _repo()
    upstream_base = settings.resolved_upstream_base_url()
    upstream_path = settings.upstream_json_path.rstrip("/")
    mode = _resolved_transform_mode(repo)
    db_mode = repo.get_setting(TRANSFORM_MODE_KEY)

    console.print()
    print_field("Агент", f"{settings.agent_host}:{settings.agent_port}")
    agent_path = settings.resolved_agent_json_path()
    print_field("URL агента", f"http://{settings.agent_host}:{settings.agent_port}")
    print_field("Путь подписки (агент)", f"{agent_path}/<sub_id>")
    print_field("Режим трансформации", _transform_mode_label(mode))
    if db_mode:
        print_field("Режим в базе", db_mode)
    else:
        print_field("Режим в базе", f"(из .env: {settings.transform_mode})")
    print_field("База данных", settings.db_path)
    print_field("Upstream", f"{upstream_base}{upstream_path}/<sub_id>" if upstream_base else "—")
    if not upstream_base:
        print_warning("Задайте UPSTREAM_BASE_URL в .env — URL sub-сервера 3x-ui")


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


def _run_settings_menu() -> None:
    while True:
        console.print()
        print_section("Настройки")
        print_menu_item(1, "Агент и upstream")
        print_menu_item(2, "Режим трансформации")
        print_menu_item(0, "Назад")
        choice = prompt_line("Выбор [0 — назад]")
        if choice == "0" or not choice:
            return
        if choice == "1":
            _do_script_settings_show()
        elif choice == "2":
            _do_edit_transform_mode(_repo())
        else:
            print_warning("Неизвестный пункт")


def _print_interactive_menu() -> None:
    print_section("Главное меню")
    print_menu_item(1, "Обзор состояния")
    print_menu_item(2, "Настройки")
    print_menu_item(3, "Служба systemd")
    print_menu_item(4, "Проверить подписку")
    print_menu_item(5, f"Запустить агент вручную (:{settings.agent_port})")
    console.print()
    print_menu_item(0, "Выход")


def run_interactive_menu() -> None:
    print_header(
        "middlewarejson",
        subtitle="прослойка JSON-подписок 3x-ui для iOS/HAPP",
    )
    try:
        print_status_bar()
    except Exception:
        pass

    while True:
        _print_interactive_menu()
        choice = text_prompt("Выбор", default="").strip()

        if choice == "0":
            console.print("[dim]До свидания[/dim]")
            break
        if not choice:
            continue
        if choice == "1":
            print_dashboard()
        elif choice == "2":
            _run_settings_menu()
        elif choice == "3":
            run_service_menu(run_service_status_menu, run_install_systemd)
        elif choice == "4":
            run_preview_interactive()
        elif choice == "5":
            _do_run_server()
        else:
            print_warning("Неизвестный пункт")


@app.callback()
def main_entry(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        run_interactive_menu()


@settings_app.command("show")
def settings_show() -> None:
    """Показать настройки агента и upstream."""
    _do_script_settings_show()


@settings_app.command("transform-mode")
def settings_transform_mode(
    mode: str = typer.Argument(
        "",
        help="passthrough или ios-fix; без аргумента — интерактивный выбор",
    ),
) -> None:
    """Переключить режим трансформации подписки (passthrough / ios-fix)."""
    if not mode:
        _do_edit_transform_mode(_repo())
        return
    try:
        _do_set_transform_mode(mode)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc


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


@service_app.command("stop")
def service_stop_cmd() -> None:
    """Остановить службу middlewarejson."""
    from app.services.systemd_service import stop_service

    ok, message = stop_service()
    if ok:
        print_success(message)
    else:
        print_error(message)
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
