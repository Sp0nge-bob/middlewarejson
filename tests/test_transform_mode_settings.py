from pathlib import Path

import pytest

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository, ClientRecord
from app.services.panel_api import (
    TRANSFORM_MODE_KEY,
    normalize_transform_mode,
    resolve_transform_mode,
)
from app.services.transform_service import TransformService

RAW_FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_normalize_transform_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        normalize_transform_mode("invalid")


def test_resolve_prefers_database_over_env_default() -> None:
    settings = Settings(transform_mode="passthrough")
    assert resolve_transform_mode(settings, "rules") == "rules"


def test_resolve_falls_back_to_env_when_db_empty() -> None:
    settings = Settings(transform_mode="rules")
    assert resolve_transform_mode(settings, None) == "rules"


def test_transform_service_uses_database_mode_without_restart() -> None:
    import json

    db_path = Path(__file__).parent / "_transform_mode_test.db"
    try:
        db_path.unlink(missing_ok=True)
    except PermissionError:
        pass
    repo = CatalogRepository(Database(db_path))
    repo.create_balancer(
        tag="pool",
        remarks="Pool",
        strategy="roundRobin",
        member_fingerprints=["vless|node1.example.com|ws|/ws-path|443|tls|"],
        scope="client",
        scope_target="client_a_sub_id12",
    )
    repo.upsert_clients(
        [ClientRecord("client_a_sub_id12", "premium", "premium@example.com", True)]
    )

    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    service = TransformService(
        Settings(transform_mode="passthrough", db_path=str(repo._db.path))
    )

    passthrough_result = service.transform("client_a_sub_id12", configs)
    passthrough_remarks = [item["remarks"] for item in passthrough_result]
    assert "NL-WS" in passthrough_remarks
    assert "hysteria-turn" not in passthrough_remarks
    assert "Pool" not in passthrough_remarks

    repo.set_setting(TRANSFORM_MODE_KEY, "rules")
    rules_result = service.transform("client_a_sub_id12", configs)
    remarks = [item["remarks"] for item in rules_result]
    assert "Pool" in remarks
    assert "NL-WS" not in remarks
    try:
        db_path.unlink(missing_ok=True)
    except PermissionError:
        pass