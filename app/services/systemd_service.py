"""Управление systemd-службой middlewarejson."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings

SERVICE_NAME = "middlewarejson"


@dataclass(frozen=True)
class ServiceScope:
    kind: str  # "system" | "user"
    unit_path: Path
    systemctl_args: tuple[str, ...]


@dataclass
class ServiceStatus:
    installed: bool
    active: str  # active | inactive | failed | unknown | not-found
    enabled: str | None = None
    pid: str | None = None
    main_pid: str | None = None
    unit_path: Path | None = None
    scope: ServiceScope | None = None
    journal_tail: list[str] = field(default_factory=list)
    error: str | None = None


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def systemctl_available() -> bool:
    return shutil.which("systemctl") is not None


def detect_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def detect_uvicorn_path(root: Path | None = None) -> Path:
    base = root or detect_project_root()
    return base / ".venv" / "bin" / "uvicorn"


def get_service_scope() -> ServiceScope:
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() == 0:
        return ServiceScope(
            kind="system",
            unit_path=Path(f"/etc/systemd/system/{SERVICE_NAME}.service"),
            systemctl_args=(),
        )
    user_unit_dir = Path.home() / ".config" / "systemd" / "user"
    return ServiceScope(
        kind="user",
        unit_path=user_unit_dir / f"{SERVICE_NAME}.service",
        systemctl_args=("--user",),
    )


def _run_systemctl(
    scope: ServiceScope,
    args: tuple[str, ...],
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = ["systemctl", *scope.systemctl_args, *args]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=check,
    )


def render_unit_file(
    settings: Settings,
    *,
    project_root: Path | None = None,
    uvicorn_path: Path | None = None,
    service_user: str | None = None,
    scope: ServiceScope | None = None,
) -> str:
    root = (project_root or detect_project_root()).resolve()
    uvicorn = (uvicorn_path or detect_uvicorn_path(root)).resolve()
    user = service_user or getpass.getuser()
    env_file = root / ".env"
    resolved_scope = scope or get_service_scope()
    wanted_by = (
        "default.target" if resolved_scope.kind == "user" else "multi-user.target"
    )
    user_line = "" if resolved_scope.kind == "user" else f"User={user}\n"

    return (
        "[Unit]\n"
        f"Description=middlewarejson — 3x-ui JSON subscription proxy\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"{user_line}"
        f"WorkingDirectory={root}\n"
        f"EnvironmentFile={env_file}\n"
        f"ExecStart={uvicorn} app.main:app "
        f"--host {settings.agent_host} --port {settings.agent_port}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        f"WantedBy={wanted_by}\n"
    )


def read_service_status(scope: ServiceScope | None = None) -> ServiceStatus:
    if not is_linux():
        return ServiceStatus(
            installed=False,
            active="unknown",
            error="Доступно только на Linux",
        )
    if not systemctl_available():
        return ServiceStatus(
            installed=False,
            active="unknown",
            error="systemctl не найден",
        )

    scope = scope or get_service_scope()
    if not scope.unit_path.exists():
        return ServiceStatus(
            installed=False,
            active="not-found",
            unit_path=scope.unit_path,
            scope=scope,
        )

    show = _run_systemctl(
        scope,
        (
            "show",
            SERVICE_NAME,
            "--property",
            "ActiveState,UnitFileState,MainPID",
            "--no-pager",
        ),
    )
    if show.returncode != 0:
        return ServiceStatus(
            installed=True,
            active="unknown",
            unit_path=scope.unit_path,
            scope=scope,
            error=(show.stderr or show.stdout or "systemctl show failed").strip(),
        )

    props: dict[str, str] = {}
    for line in show.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()

    journal_tail: list[str] = []
    if shutil.which("journalctl"):
        journal_args = ["journalctl", *scope.systemctl_args, "-u", SERVICE_NAME, "-n", "5", "--no-pager"]
        journal = subprocess.run(journal_args, capture_output=True, text=True)
        if journal.returncode == 0 and journal.stdout.strip():
            journal_tail = journal.stdout.strip().splitlines()

    main_pid = props.get("MainPID")
    return ServiceStatus(
        installed=True,
        active=props.get("ActiveState", "unknown"),
        enabled=props.get("UnitFileState"),
        main_pid=None if main_pid in (None, "", "0") else main_pid,
        unit_path=scope.unit_path,
        scope=scope,
        journal_tail=journal_tail,
    )


def start_service(scope: ServiceScope | None = None) -> tuple[bool, str]:
    scope = scope or get_service_scope()
    result = _run_systemctl(scope, ("start", SERVICE_NAME))
    if result.returncode == 0:
        return True, "Служба запущена"
    message = (result.stderr or result.stdout or "start failed").strip()
    return False, message


def restart_service(scope: ServiceScope | None = None) -> tuple[bool, str]:
    scope = scope or get_service_scope()
    result = _run_systemctl(scope, ("restart", SERVICE_NAME))
    if result.returncode == 0:
        return True, "Служба перезапущена"
    message = (result.stderr or result.stdout or "restart failed").strip()
    return False, message


def stop_service(scope: ServiceScope | None = None) -> tuple[bool, str]:
    scope = scope or get_service_scope()
    result = _run_systemctl(scope, ("stop", SERVICE_NAME))
    if result.returncode == 0:
        return True, "Служба остановлена"
    message = (result.stderr or result.stdout or "stop failed").strip()
    return False, message


def install_service(
    settings: Settings,
    *,
    start_after: bool = False,
    project_root: Path | None = None,
) -> tuple[bool, str]:
    if not is_linux():
        return False, "Доступно только на Linux"
    if not systemctl_available():
        return False, "systemctl не найден"

    root = (project_root or detect_project_root()).resolve()
    uvicorn = detect_uvicorn_path(root)
    env_file = root / ".env"

    if not uvicorn.is_file():
        return False, f"Не найден {uvicorn} — создайте venv и установите зависимости"
    if not env_file.is_file():
        return False, f"Не найден {env_file}"

    scope = get_service_scope()
    scope.unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_content = render_unit_file(
        settings,
        project_root=root,
        uvicorn_path=uvicorn,
        scope=scope,
    )
    scope.unit_path.write_text(unit_content, encoding="utf-8")

    reload = _run_systemctl(scope, ("daemon-reload",))
    if reload.returncode != 0:
        return False, (reload.stderr or reload.stdout or "daemon-reload failed").strip()

    enable = _run_systemctl(scope, ("enable", SERVICE_NAME))
    if enable.returncode != 0:
        return False, (enable.stderr or enable.stdout or "enable failed").strip()

    if start_after:
        started, message = start_service(scope)
        if not started:
            return False, message

    if scope.kind == "user":
        linger_hint = (
            f"Для работы без входа в систему: loginctl enable-linger {getpass.getuser()}"
        )
        return True, f"Служба установлена (user). {linger_hint}"

    return True, "Служба установлена (system)"