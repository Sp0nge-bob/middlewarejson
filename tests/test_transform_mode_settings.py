from pathlib import Path

import pytest

from app.config import Settings
from app.db.database import Database
from app.db.repository import SettingsRepository
from app.services.mode import (
    TRANSFORM_MODE_KEY,
    normalize_transform_mode,
    resolve_transform_mode,
)
from app.services.transform_service import TransformService
from app.transformers.ios_fix import apply_ios_fix


def test_normalize_transform_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        normalize_transform_mode("invalid")
    with pytest.raises(ValueError):
        normalize_transform_mode("rules")


def test_resolve_prefers_database_over_env_default() -> None:
    settings = Settings(transform_mode="passthrough")
    assert resolve_transform_mode(settings, "ios-fix") == "ios-fix"


def test_resolve_falls_back_to_env_when_db_empty() -> None:
    settings = Settings(transform_mode="ios-fix")
    assert resolve_transform_mode(settings, None) == "ios-fix"


def test_resolve_unknown_mode_falls_back_to_passthrough() -> None:
    settings = Settings(transform_mode="passthrough")
    assert resolve_transform_mode(settings, "ios-fix-typo") == "passthrough"


def test_transform_service_uses_database_mode_without_restart(tmp_path: Path) -> None:
    payload = [
        {
            "remarks": "NL",
            "inbounds": [{"protocol": "mixed", "tag": "mixed"}],
            "outbounds": [{"protocol": "vless", "tag": "proxy"}],
        }
    ]
    repo = SettingsRepository(Database(tmp_path / "mode.db"))
    service = TransformService(
        Settings(transform_mode="passthrough", db_path=str(repo._db.path))
    )

    passthrough = service.transform("sub", payload)
    assert passthrough[0]["inbounds"][0]["protocol"] == "mixed"

    repo.set_setting(TRANSFORM_MODE_KEY, "ios-fix")
    fixed = service.transform("sub", payload)
    assert fixed[0]["inbounds"][0]["protocol"] == "socks"
    assert apply_ios_fix(payload)[0]["inbounds"][0]["protocol"] == "socks"
