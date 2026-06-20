import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.services import systemd_service as svc


def test_render_unit_file_uses_settings_and_paths(tmp_path: Path) -> None:
    uvicorn = tmp_path / ".venv" / "bin" / "uvicorn"
    uvicorn.parent.mkdir(parents=True)
    uvicorn.write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / ".env").write_text("AGENT_PORT=8085\n", encoding="utf-8")

    settings = Settings(agent_host="127.0.0.1", agent_port=8085)
    scope = svc.ServiceScope(
        kind="system",
        unit_path=Path("/etc/systemd/system/middlewarejson.service"),
        systemctl_args=(),
    )
    content = svc.render_unit_file(
        settings,
        project_root=tmp_path,
        uvicorn_path=uvicorn,
        service_user="deploy",
        scope=scope,
    )

    env_file = tmp_path.resolve() / ".env"
    assert "User=deploy" in content
    assert f"WorkingDirectory={tmp_path.resolve()}" in content
    assert f"EnvironmentFile={env_file}" in content
    assert "--host 127.0.0.1 --port 8085" in content
    assert str(uvicorn.resolve()) in content


def test_get_service_scope_user_when_not_root(monkeypatch) -> None:
    monkeypatch.setattr(svc.os, "geteuid", lambda: 1000, raising=False)
    scope = svc.get_service_scope()
    assert scope.kind == "user"
    assert scope.unit_path.name == "middlewarejson.service"
    assert scope.systemctl_args == ("--user",)


def test_get_service_scope_system_when_root(monkeypatch) -> None:
    monkeypatch.setattr(svc.os, "geteuid", lambda: 0, raising=False)
    scope = svc.get_service_scope()
    assert scope.kind == "system"
    assert scope.unit_path.as_posix() == "/etc/systemd/system/middlewarejson.service"


def test_read_service_status_not_installed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(svc, "is_linux", lambda: True)
    monkeypatch.setattr(svc, "systemctl_available", lambda: True)
    scope = svc.ServiceScope(
        kind="user",
        unit_path=tmp_path / "missing.service",
        systemctl_args=("--user",),
    )
    status = svc.read_service_status(scope)
    assert status.installed is False
    assert status.active == "not-found"


def test_read_service_status_active(monkeypatch) -> None:
    monkeypatch.setattr(svc, "is_linux", lambda: True)
    monkeypatch.setattr(svc, "systemctl_available", lambda: True)

    scope = svc.ServiceScope(
        kind="system",
        unit_path=Path("/etc/systemd/system/middlewarejson.service"),
        systemctl_args=(),
    )

    def fake_exists(self: Path) -> bool:
        return str(self).endswith("middlewarejson.service")

    monkeypatch.setattr(Path, "exists", fake_exists)

    def fake_run(command, **kwargs):
        if command[:2] == ["systemctl", "show"]:
            return MagicMock(
                returncode=0,
                stdout="ActiveState=active\nUnitFileState=enabled\nMainPID=1234\n",
                stderr="",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(svc.subprocess, "run", fake_run)
    monkeypatch.setattr(svc.shutil, "which", lambda _: None)

    status = svc.read_service_status(scope)
    assert status.installed is True
    assert status.active == "active"
    assert status.enabled == "enabled"
    assert status.main_pid == "1234"


def test_install_service_requires_uvicorn(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(svc, "is_linux", lambda: True)
    monkeypatch.setattr(svc, "systemctl_available", lambda: True)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    settings = Settings()
    ok, message = svc.install_service(settings, project_root=tmp_path)
    assert ok is False
    assert "uvicorn" in message.lower()


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_not_linux(platform: str, monkeypatch) -> None:
    monkeypatch.setattr(svc.sys, "platform", platform)
    status = svc.read_service_status()
    assert status.error == "Доступно только на Linux"


def test_stop_service_success(monkeypatch) -> None:
    scope = svc.ServiceScope(
        kind="system",
        unit_path=Path("/etc/systemd/system/middlewarejson.service"),
        systemctl_args=(),
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(svc.subprocess, "run", fake_run)
    ok, message = svc.stop_service(scope)
    assert ok is True
    assert message == "Служба остановлена"
    assert calls == [["systemctl", "stop", "middlewarejson"]]


def test_stop_service_failure(monkeypatch) -> None:
    scope = svc.ServiceScope(
        kind="user",
        unit_path=Path.home() / ".config/systemd/user/middlewarejson.service",
        systemctl_args=("--user",),
    )

    def fake_run(command, **kwargs):
        return MagicMock(returncode=1, stdout="", stderr="Unit not running")

    monkeypatch.setattr(svc.subprocess, "run", fake_run)
    ok, message = svc.stop_service(scope)
    assert ok is False
    assert message == "Unit not running"