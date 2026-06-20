import json
from pathlib import Path

import pytest

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.services.client_sync import sync_clients

GROUPS_FIXTURE = Path(__file__).parent / "fixtures" / "panel_groups_list.json"
EMAILS_FIXTURE = Path(__file__).parent / "fixtures" / "panel_group_emails.json"
LOOKUP_FIXTURE = Path(__file__).parent / "fixtures" / "panel_clients_lookup.json"


class FakePanelClient:
    def __init__(self) -> None:
        self.groups = json.loads(GROUPS_FIXTURE.read_text(encoding="utf-8"))
        self.emails = json.loads(EMAILS_FIXTURE.read_text(encoding="utf-8"))
        self.lookup = json.loads(LOOKUP_FIXTURE.read_text(encoding="utf-8"))

    def fetch_groups(self) -> list[dict]:
        return self.groups

    def fetch_group_emails(self, group_name: str) -> list[dict]:
        return [{"email": email} for email in self.emails.get(group_name, [])]

    def fetch_clients_list(self) -> list[dict]:
        return self.lookup

    def fetch_client_by_email(self, email: str) -> dict | None:
        for row in self.lookup:
            if row.get("email") == email:
                return row
        return None


@pytest.fixture
def repo(tmp_path: Path) -> CatalogRepository:
    return CatalogRepository(Database(tmp_path / "test.db"))


def test_sync_clients_via_groups_and_emails(
    repo: CatalogRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakePanelClient()
    repo.set_setting("panel_api_token", "test-token")

    settings = Settings(
        panel_api_token="test-token",
        db_path=str(repo._db.path),
    )

    monkeypatch.setattr(
        "app.services.client_sync._make_panel_client",
        lambda _settings, _repo: fake,
    )

    result = sync_clients(settings, repo)
    assert result["groups"] == 2
    assert result["groups_with_clients"] == 2
    assert result["upserted"] == 2
    assert repo.list_groups() == ["basic", "premium"]

    assert repo.get_group_for_sub_id("client_a_sub_id12") == "premium"
    assert repo.get_group_for_sub_id("client_b_sub_id12") == "basic"
    assert repo.get_group_for_sub_id("any_sub_id_12345") is None
    assert repo.get_group_for_sub_id("disabled_sub_id") is None

    premium_clients = repo.list_clients_by_group("premium")
    assert len(premium_clients) == 1
    assert premium_clients[0].sub_id == "client_a_sub_id12"


def test_sync_clients_removes_stale_entries(
    repo: CatalogRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakePanelClient()
    settings = Settings(panel_api_token="test-token", db_path=str(repo._db.path))

    monkeypatch.setattr(
        "app.services.client_sync._make_panel_client",
        lambda _settings, _repo: fake,
    )
    sync_clients(settings, repo)

    fake.emails = {"premium": ["premium@example.com"]}
    result = sync_clients(settings, repo)
    assert result["removed"] == 1
    assert repo.get_group_for_sub_id("client_b_sub_id12") is None