"""Операторские экраны CLI: обзор и превью подписки."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

import httpx
from rich import box
from rich.table import Table

from app.cli_ui import (
    CANCEL_HINT,
    console,
    is_exit_choice,
    print_error,
    print_field,
    print_info,
    print_menu_item,
    print_section,
    print_warning,
    prompt_line,
    text_prompt,
)
from app.config import settings
from app.db.database import Database
from app.db.repository import SettingsRepository
from app.models.subscription import (
    parse_subscription_reference,
    validate_payload,
    validate_sub_id,
)
from app.services.mode import TRANSFORM_MODE_KEY, resolve_transform_mode
from app.services.systemd_service import (
    get_service_scope,
    is_linux,
    read_service_status,
    systemctl_available,
)
from app.services.transform_service import TransformService
from app.services.upstream import UpstreamClient, UpstreamError

_SYSTEM_PROTOCOLS = frozenset({"freedom", "blackhole", "dns"})


def _repo() -> SettingsRepository:
    return SettingsRepository(Database(settings.db_path))


def _transform_mode_label(mode: str) -> str:
    if mode == "ios-fix-beta":
        return "ios-fix-beta — ios-fix + перехват DNS в прокси"
    if mode == "ios-fix":
        return "ios-fix — mixed→socks, балансер 3x-ui под iOS"
    return "passthrough — без изменений"


def _probe_health() -> tuple[bool, str]:
    url = f"http://{settings.agent_host}:{settings.agent_port}/health"
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(url)
        if response.status_code == 200 and response.json().get("status") == "ok":
            return True, "ok"
        return False, f"HTTP {response.status_code}"
    except httpx.HTTPError:
        return False, "не отвечает"


def _service_label() -> str:
    status = read_service_status()
    if status.error and not status.installed:
        return status.error
    if not status.installed:
        return "не установлена"
    labels = {
        "active": "работает",
        "inactive": "остановлена",
        "failed": "ошибка",
        "not-found": "не установлена",
    }
    return labels.get(status.active, status.active)


def print_status_bar(repo: SettingsRepository | None = None) -> None:
    repo = repo or _repo()
    mode = resolve_transform_mode(settings, repo.get_setting(TRANSFORM_MODE_KEY))
    health_ok, health = _probe_health()
    health_text = f"[green]{health}[/green]" if health_ok else f"[yellow]{health}[/yellow]"
    service = _service_label()
    service_text = (
        f"[green]{service}[/green]" if service == "работает" else f"[yellow]{service}[/yellow]"
    )
    mode_text = (
        f"[green]{mode}[/green]" if mode in ("ios-fix", "ios-fix-beta") else f"[yellow]{mode}[/yellow]"
    )
    console.print(
        f"  режим {mode_text}  ·  служба {service_text}  ·  health {health_text}"
    )


def print_dashboard() -> None:
    repo = _repo()
    mode = resolve_transform_mode(settings, repo.get_setting(TRANSFORM_MODE_KEY))
    upstream_base = settings.resolved_upstream_base_url()
    upstream_path = settings.upstream_json_path.rstrip("/")
    agent_path = settings.resolved_agent_json_path()
    health_ok, health = _probe_health()

    console.print()
    print_section("Обзор")
    print_field("Режим", _transform_mode_label(mode))
    print_field("Агент", f"http://{settings.agent_host}:{settings.agent_port}{agent_path}/<sub_id>")
    print_field("Upstream", f"{upstream_base}{upstream_path}/<sub_id>" if upstream_base else "—")
    print_field("Служба", _service_label())
    print_field("Health", "ok" if health_ok else health)
    if not upstream_base:
        print_warning("Задайте UPSTREAM_BASE_URL в .env")
    if not health_ok:
        print_info("Агент не слушает /health — установите службу или запустите вручную")


def _proxy_outbounds(config: dict[str, Any]) -> list[dict[str, Any]]:
    outbounds = config.get("outbounds", [])
    if not isinstance(outbounds, list):
        return []
    result: list[dict[str, Any]] = []
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        protocol = str(outbound.get("protocol", ""))
        tag = str(outbound.get("tag", ""))
        if tag == "proxy" or protocol not in _SYSTEM_PROTOCOLS:
            result.append(outbound)
    return result


def summarize_profiles(payload: Any) -> list[dict[str, Any]]:
    configs = payload if isinstance(payload, list) else [payload]
    rows: list[dict[str, Any]] = []
    for index, config in enumerate(configs):
        if not isinstance(config, dict):
            continue
        routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}
        balancers = routing.get("balancers") if isinstance(routing.get("balancers"), list) else []
        first = balancers[0] if balancers and isinstance(balancers[0], dict) else {}
        selector = first.get("selector") if isinstance(first.get("selector"), list) else []
        proxies = _proxy_outbounds(config)
        rows.append(
            {
                "index": index,
                "remarks": str(config.get("remarks") or f"#{index}"),
                "kind": "пул" if balancers else "сервер",
                "proxies": len(proxies),
                "selector": [str(item) for item in selector],
                "fallback": str(first.get("fallbackTag") or ""),
                "strategy": str((first.get("strategy") or {}).get("type") or "")
                if isinstance(first.get("strategy"), dict)
                else "",
            }
        )
    return rows


def _print_profile_table(rows: list[dict[str, Any]]) -> None:
    table = Table(title="Профили в JSON", box=box.SIMPLE_HEAD)
    table.add_column("#", justify="right")
    table.add_column("Название")
    table.add_column("Тип")
    table.add_column("Proxy", justify="right")
    table.add_column("Стратегия")
    table.add_column("Fallback")
    for row in rows:
        table.add_row(
            str(row["index"]),
            str(row["remarks"]),
            str(row["kind"]),
            str(row["proxies"]),
            str(row["strategy"] or "—"),
            str(row["fallback"] or "—"),
        )
    console.print(table)


def _warn_profiles(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if row["kind"] == "пул" and not row["selector"]:
            print_warning(f"[{row['index']}] {row['remarks']}: пустой selector — туннель будет чёрной дырой")
        if row["kind"] == "пул" and row["proxies"] == 0:
            print_warning(f"[{row['index']}] {row['remarks']}: нет proxy outbound")


def _fetch_from_agent(sub_id: str) -> tuple[int, Any, str] | None:
    path = settings.resolved_agent_json_path()
    url = f"http://{settings.agent_host}:{settings.agent_port}{path}/{sub_id}"
    try:
        with httpx.Client(timeout=settings.request_timeout_sec) as client:
            response = client.get(
                url,
                headers={"Accept": "application/json", "User-Agent": "Happ/1.0"},
            )
    except httpx.HTTPError:
        return None
    error_text = (response.text or "").strip().replace("\n", " ")[:200]
    if response.status_code != 200:
        return response.status_code, None, error_text
    try:
        return 200, response.json(), ""
    except ValueError:
        return 200, None, error_text or "ответ не JSON"


async def _fetch_upstream(sub_id: str) -> tuple[int, str]:
    client = UpstreamClient(settings, base_url=settings.resolved_upstream_base_url())
    result = await client.fetch(sub_id)
    return result.status_code, result.body


def preview_subscription(raw_ref: str) -> None:
    try:
        sub_id = parse_subscription_reference(raw_ref)
    except ValueError as exc:
        print_error(str(exc))
        return
    if not validate_sub_id(sub_id):
        print_error("Некорректный sub_id")
        return

    repo = _repo()
    mode = resolve_transform_mode(settings, repo.get_setting(TRANSFORM_MODE_KEY))

    console.print()
    print_field("sub_id", sub_id)
    print_field("Режим", _transform_mode_label(mode))

    payload: Any = None
    source = ""
    agent = _fetch_from_agent(sub_id)
    if agent is not None:
        status, body, error_text = agent
        if status == 200 and body is not None:
            payload = body
            source = "агент (как получит телефон)"
        else:
            detail = f" — {error_text}" if error_text else ""
            print_warning(f"Агент ответил HTTP {status}{detail}")

    if payload is None:
        try:
            status, body = asyncio.run(_fetch_upstream(sub_id))
        except UpstreamError as exc:
            print_error(f"Upstream недоступен: {exc}")
            return
        if status != 200:
            print_error(f"Upstream HTTP {status}")
            return
        try:
            raw_payload = json.loads(body)
            validate_payload(raw_payload)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            print_error(f"Невалидный JSON upstream: {exc}")
            return
        payload = TransformService(settings).transform(sub_id, raw_payload)
        source = "upstream + локальная трансформация"

    print_field("Источник", source)
    rows = summarize_profiles(payload)
    if not rows:
        print_warning("В JSON нет профилей")
        return
    _print_profile_table(rows)
    _warn_profiles(rows)
    print_info(f"Профилей: {len(rows)}")


def run_preview_interactive() -> None:
    print_section("Проверка подписки")
    print_info("Вставьте sub_id или JSON-ссылку из карточки клиента 3x-ui / HAPP")
    raw = text_prompt(f"sub_id или URL, {CANCEL_HINT}", default="").strip()
    if not raw or is_exit_choice(raw):
        return
    preview_subscription(raw)


def show_service_logs(*, lines: int = 40) -> None:
    if not is_linux() or not systemctl_available():
        print_warning("journalctl доступен только на Linux с systemd")
        return
    scope = get_service_scope()
    command = [
        "journalctl",
        *scope.systemctl_args,
        "-u",
        "middlewarejson",
        "-n",
        str(lines),
        "--no-pager",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print_error((result.stderr or result.stdout or "journalctl failed").strip())
        return
    console.print()
    console.print(result.stdout or "[dim]логов нет[/dim]")


def run_service_menu(status_menu, install_menu) -> None:
    while True:
        console.print()
        print_section("Служба")
        print_menu_item(1, "Статус")
        print_menu_item(2, "Установить systemd")
        print_menu_item(3, "Логи")
        print_menu_item(0, "Назад")
        choice = prompt_line("Выбор [0 — назад]")
        if choice == "0" or not choice:
            return
        if choice == "1":
            status_menu()
        elif choice == "2":
            install_menu()
        elif choice == "3":
            show_service_logs()
        else:
            print_warning("Неизвестный пункт")
