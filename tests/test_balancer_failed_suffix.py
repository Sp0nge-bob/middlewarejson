import json
from pathlib import Path

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository, ClientRecord
from app.services.transform_service import TransformService

RAW_FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_partial_balancer_members_mark_profile_failed(tmp_path: Path) -> None:
    repo = CatalogRepository(Database(tmp_path / "failed.db"))
    present_fp = "vless|node1.example.com|ws|/ws-path|443|tls|"
    missing_fp = "vless|missing.example.com|ws|/ws-path|443|tls|"

    repo.create_balancer(
        tag="testbalance",
        remarks="TESTBALANCE",
        strategy="roundRobin",
        member_fingerprints=[present_fp, missing_fp],
        scope="client",
        scope_target="client_a_sub_id12",
    )
    repo.upsert_clients(
        [
            ClientRecord("client_a_sub_id12", "premium", "premium@example.com", True),
        ]
    )

    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    service = TransformService(
        Settings(transform_mode="rules", db_path=str(repo._db.path))
    )
    result = service.transform("client_a_sub_id12", configs)
    remarks = [item["remarks"] for item in result]

    assert "TESTBALANCE - Failed" in remarks
    assert "TESTBALANCE" not in remarks