"""CLI: состояние и установка systemd-службы."""

from __future__ import annotations

import httpx

from app.cli_ui import (
    confirm_prompt,
    console,
    print_error,
    print_field,
    print_info,
    print_menu_item,
    print_success,
    print_warning,
    prompt_line,
)
from app.config import settings
from app.services.systemd_service import (
    detect_project_root,
    detect_uvicorn_path,
    install_service,
    is_linux,
    read_service_status,
    render_unit_file,
    restart_service,
    start_service,
    systemctl_available,
)


def _format_active_state(active: str) -> str:
    labels = {
        "active": "[green]работает[/green]",
        "inactive": "[yellow]остановлена[/yellow]",
        "failed": "[red]ошибка[/red]",
        "not-found": "[dim]не установлена[/dim]",
    }
    return labels.get(active, active)


def _probe_health() -> tuple[bool, str]:
    url = f"http://{settings.agent_host}:{settings.agent_port}/health"
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(url)
        if response.status_code == 200 and response.json().get("status") == "ok":
            return True, f"HTTP 200 — {url}"
        return False, f"HTTP {response.status_code} — {url}"
    except httpx.HTTPError as exc:
        return False, f"{url} — {exc}"


def _print_service_status() -> bool:
    """Показать статус. False — нельзя продолжать (не Linux / нет systemctl)."""
    if not is_linux():
        print_warning("Доступно только на Linux с systemd")
        return False
    if not systemctl_available():
        print_warning("systemctl не найден в PATH")
        return False

    status = read_service_status()
    if status.error and not status.installed:
        print_error(status.error)
        return False

    console.print()
    scope_label = status.scope.kind if status.scope else "—"
    print_field("Область", f"systemd ({scope_label})")
    print_field("Unit-файл", str(status.unit_path) if status.unit_path else "—")
    print_field("Установлена", "да" if status.installed else "нет")
    print_field("Состояние", _format_active_state(status.active))
    if status.enabled:
        print_field("Автозапуск", status.enabled)
    if status.main_pid:
        print_field("PID", status.main_pid)

    health_ok, health_msg = _probe_health()
    print_field("Health", health_msg)
    if not health_ok and status.active == "active":
        print_warning("Служба active, но /health не отвечает — проверьте порт и логи")

    if status.journal_tail:
        console.print()
        console.print("[dim]Последние строки journal:[/dim]")
        for line in status.journal_tail[-5:]:
            console.print(f"  [dim]{line}[/dim]")

    if status.error:
        print_warning(status.error)

    return True


def run_service_status_menu() -> None:
    if not _print_service_status():
        return

    status = read_service_status()
    if not status.installed:
        print_info("Установите службу через п. 5 в меню «Настройки»")
        return

    console.print()
    print_menu_item(0, "Назад")
    if status.active != "active":
        print_menu_item(1, "Запустить")
    else:
        print_menu_item(1, "Запустить (уже работает)")
    print_menu_item(2, "Перезапустить")

    choice = prompt_line("Выбор [0 — назад]")
    if choice == "0" or not choice:
        return
    if choice == "1":
        ok, message = start_service(status.scope)
        if ok:
            print_success(message)
        else:
            print_error(message)
    elif choice == "2":
        ok, message = restart_service(status.scope)
        if ok:
            print_success(message)
        else:
            print_error(message)
    else:
        print_warning("Неизвестный пункт")


def run_install_systemd() -> None:
    if not is_linux():
        print_warning("Доступно только на Linux с systemd")
        return
    if not systemctl_available():
        print_warning("systemctl не найден в PATH")
        return

    root = detect_project_root()
    uvicorn = detect_uvicorn_path(root)
    env_file = root / ".env"

    console.print()
    print_field("Каталог проекта", str(root))
    print_field("Uvicorn", str(uvicorn))
    print_field("Env-файл", str(env_file))

    if not uvicorn.is_file():
        print_error("Сначала создайте .venv и установите зависимости")
        return
    if not env_file.is_file():
        print_error("Создайте .env (cp .env.example .env)")
        return

    from app.services.systemd_service import get_service_scope

    scope = get_service_scope()
    unit_preview = render_unit_file(
        settings,
        project_root=root,
        uvicorn_path=uvicorn,
        scope=scope,
    )
    console.print()
    console.print("[bold]Будет создан unit-файл:[/bold]")
    console.print(f"[dim]{unit_preview}[/dim]")

    if not confirm_prompt("Установить службу systemd?", default=False):
        print_info("Отменено")
        return

    start_after = confirm_prompt("Запустить службу сразу после установки?", default=True)
    ok, message = install_service(settings, start_after=start_after, project_root=root)
    if ok:
        print_success(message)
        print_info(f"Проверка: systemctl {'--user ' if 'user' in message else ''}status middlewarejson")
    else:
        print_error(message)