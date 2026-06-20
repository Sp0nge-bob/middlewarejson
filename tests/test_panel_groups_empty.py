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
    def __init__(self, groups: list[dict], emails: dict[str, list[str]], lookup: list[dict]) -> None:
        self.groups = groups
        self.emails = emails
        self.lookup = lookup

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


def test_empty_group_is_listed_after_sync(
    repo: CatalogRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = json.loads(GROUPS_FIXTURE.read_text(encoding="utf-8"))
    groups.append({"name": "empty-group", "count": 0})
    emails = json.loads(EMAILS_FIXTURE.read_text(encoding="utf-8"))
    lookup = json.loads(LOOKUP_FIXTURE.read_text(encoding="utf-8"))

    fake = FakePanelClient(groups, emails, lookup)
    settings = Settings(panel_api_token="test-token", db_path=str(repo._db.path))
    monkeypatch.setattr(
        "app.services.client_sync._make_panel_client",
        lambda _settings, _repo: fake,
    )

    result = sync_clients(settings, repo)
    assert result["groups"] == 3
    assert result["groups_with_clients"] == 2
    assert repo.list_groups() == ["basic", "empty-group", "premium"]
    assert len(repo.list_clients_by_group("empty-group")) == 0