import json
from pathlib import Path

import pytest

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.services.client_sync import sync_clients

CLIENTS_FIXTURE = Path(__file__).parent / "fixtures" / "panel_clients_list.json"


@pytest.fixture
def repo(tmp_path: Path) -> CatalogRepository:
    return CatalogRepository(Database(tmp_path / "test.db"))


def test_sync_clients_upserts_groups(repo: CatalogRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    clients = json.loads(CLIENTS_FIXTURE.read_text(encoding="utf-8"))
    repo.set_setting("panel_api_token", "test-token")

    settings = Settings(
        panel_api_token="test-token",
        db_path=str(repo._db.path),
    )

    monkeypatch.setattr(
        "app.services.client_sync.fetch_panel_clients_sync",
        lambda _settings, _repo: clients,
    )

    result = sync_clients(settings, repo)
    assert result["upserted"] == 3
    assert result["groups"] == 2

    assert repo.get_group_for_sub_id("client_a_sub_id12") == "premium"
    assert repo.get_group_for_sub_id("client_b_sub_id12") == "basic"
    assert repo.get_group_for_sub_id("any_sub_id_12345") is None
    assert repo.get_group_for_sub_id("disabled_sub_id") is None

    premium_clients = repo.list_clients_by_group("premium")
    assert len(premium_clients) == 1
    assert premium_clients[0].sub_id == "client_a_sub_id12"


def test_sync_clients_removes_stale_entries(repo: CatalogRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    clients = json.loads(CLIENTS_FIXTURE.read_text(encoding="utf-8"))
    settings = Settings(panel_api_token="test-token", db_path=str(repo._db.path))

    monkeypatch.setattr(
        "app.services.client_sync.fetch_panel_clients_sync",
        lambda _settings, _repo: clients,
    )
    sync_clients(settings, repo)

    reduced = [clients[0]]
    monkeypatch.setattr(
        "app.services.client_sync.fetch_panel_clients_sync",
        lambda _settings, _repo: reduced,
    )
    result = sync_clients(settings, repo)
    assert result["removed"] == 2
    assert repo.get_group_for_sub_id("client_b_sub_id12") is None