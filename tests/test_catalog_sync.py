import json
from pathlib import Path

import pytest

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.services.catalog_sync import configs_to_inbounds, sync_catalog

RAW_FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"
PANEL_FIXTURE = Path(__file__).parent / "fixtures" / "panel_inbounds_list.json"


@pytest.fixture
def repo(tmp_path: Path) -> CatalogRepository:
    return CatalogRepository(Database(tmp_path / "test.db"))


def test_configs_to_inbounds() -> None:
    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    inbounds = configs_to_inbounds(configs)
    assert len(inbounds) == 10


def test_sync_upserts_and_deactivates(repo: CatalogRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    panel_inbounds = json.loads(PANEL_FIXTURE.read_text(encoding="utf-8"))
    repo.set_setting("panel_api_token", "test-token")

    settings = Settings(
        panel_api_token="test-token",
        db_path=str(repo._db.path),
    )

    monkeypatch.setattr(
        "app.services.catalog_sync.fetch_panel_inbounds_sync",
        lambda _settings, _repo: panel_inbounds,
    )

    result = sync_catalog(settings, repo)
    assert result["upserted"] == 10
    assert result["total_active"] == 10

    active = repo.list_inbounds(active_only=True)
    assert len(active) == 10
    assert all(row["panel_inbound_id"] is not None for row in active)

    reduced = panel_inbounds[:8]
    monkeypatch.setattr(
        "app.services.catalog_sync.fetch_panel_inbounds_sync",
        lambda _settings, _repo: reduced,
    )
    sync_catalog(settings, repo)
    active = repo.list_inbounds(active_only=True)
    assert len(active) == 8
    all_rows = repo.list_inbounds(active_only=False)
    assert len(all_rows) == 10
    assert sum(1 for row in all_rows if not row["is_active"]) == 2


def test_get_fingerprints_by_panel_ids(repo: CatalogRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    panel_inbounds = json.loads(PANEL_FIXTURE.read_text(encoding="utf-8"))
    settings = Settings(panel_api_token="test-token", db_path=str(repo._db.path))

    monkeypatch.setattr(
        "app.services.catalog_sync.fetch_panel_inbounds_sync",
        lambda _settings, _repo: panel_inbounds,
    )
    sync_catalog(settings, repo)

    fingerprints = repo.get_fingerprints_by_panel_ids([1, 7])
    assert len(fingerprints) == 2
    assert all("|" in fingerprint for fingerprint in fingerprints)