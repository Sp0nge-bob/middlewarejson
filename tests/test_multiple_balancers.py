import json
from pathlib import Path

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository, ClientRecord
from app.services.transform_service import TransformService

RAW_FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_multiple_balancers_same_group(tmp_path: Path) -> None:
    repo = CatalogRepository(Database(tmp_path / "multi_group.db"))
    nl_fp = "vless|node1.example.com|ws|/ws-path|443|tls|"
    us_fp = "vless|node5.example.com|ws|/ws-path|443|tls|"

    repo.create_balancer(
        tag="nl-pool",
        remarks="NL Balance",
        strategy="roundRobin",
        member_fingerprints=[nl_fp],
        scope="group",
        scope_target="premium",
    )
    repo.create_balancer(
        tag="us-pool",
        remarks="USA Balance",
        strategy="leastLoad",
        member_fingerprints=[us_fp],
        scope="group",
        scope_target="premium",
    )
    repo.upsert_clients(
        [
            ClientRecord("client_a_sub_id12", "premium", "premium@example.com", True),
        ]
    )

    tags = repo.get_balancer_tags_for_sub_id("client_a_sub_id12")
    assert tags == ["nl-pool", "us-pool"]

    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    service = TransformService(Settings(transform_mode="rules", db_path=str(repo._db.path)))
    result = service.transform("client_a_sub_id12", configs)
    remarks = [item["remarks"] for item in result]

    assert "NL Balance" in remarks
    assert "USA Balance" in remarks


def test_multiple_balancers_all_scope(tmp_path: Path) -> None:
    repo = CatalogRepository(Database(tmp_path / "multi_all.db"))
    nl_fp = "vless|node1.example.com|ws|/ws-path|443|tls|"
    us_fp = "vless|node5.example.com|ws|/ws-path|443|tls|"

    repo.create_balancer(
        tag="global-nl",
        remarks="Global NL",
        strategy="roundRobin",
        member_fingerprints=[nl_fp],
        scope="all",
    )
    repo.create_balancer(
        tag="global-us",
        remarks="Global USA",
        strategy="random",
        member_fingerprints=[us_fp],
        scope="all",
    )
    repo.upsert_clients(
        [
            ClientRecord("any_sub_id_12345", "", "nogroup@example.com", True),
        ]
    )

    tags = repo.get_balancer_tags_for_sub_id("any_sub_id_12345")
    assert tags == ["global-nl", "global-us"]

    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    service = TransformService(Settings(transform_mode="rules", db_path=str(repo._db.path)))
    result = service.transform("any_sub_id_12345", configs)
    remarks = [item["remarks"] for item in result]

    assert "Global NL" in remarks
    assert "Global USA" in remarks


def test_client_group_and_all_balancers_combine(tmp_path: Path) -> None:
    repo = CatalogRepository(Database(tmp_path / "combined.db"))
    nl_fp = "vless|node1.example.com|ws|/ws-path|443|tls|"
    us_fp = "vless|node5.example.com|ws|/ws-path|443|tls|"

    repo.create_balancer(
        tag="group-pool",
        remarks="Group Pool",
        strategy="roundRobin",
        member_fingerprints=[nl_fp],
        scope="group",
        scope_target="premium",
    )
    repo.create_balancer(
        tag="solo-pool",
        remarks="Solo Pool",
        strategy="leastLoad",
        member_fingerprints=[us_fp],
        scope="client",
        scope_target="client_a_sub_id12",
    )
    repo.create_balancer(
        tag="global-pool",
        remarks="Global Pool",
        strategy="leastPing",
        member_fingerprints=[nl_fp],
        scope="all",
    )
    repo.upsert_clients(
        [
            ClientRecord("client_a_sub_id12", "premium", "premium@example.com", True),
            ClientRecord("client_b_sub_id12", "premium", "basic@example.com", True),
        ]
    )

    client_a_tags = repo.get_balancer_tags_for_sub_id("client_a_sub_id12")
    assert client_a_tags == ["solo-pool", "group-pool", "global-pool"]

    client_b_tags = repo.get_balancer_tags_for_sub_id("client_b_sub_id12")
    assert client_b_tags == ["group-pool", "global-pool"]

    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    service = TransformService(Settings(transform_mode="rules", db_path=str(repo._db.path)))

    solo_result = service.transform("client_a_sub_id12", configs)
    solo_remarks = [item["remarks"] for item in solo_result]
    assert "Solo Pool" in solo_remarks
    assert "Group Pool" in solo_remarks
    assert "Global Pool" in solo_remarks

    group_result = service.transform("client_b_sub_id12", configs)
    group_remarks = [item["remarks"] for item in group_result]
    assert "Group Pool" in group_remarks
    assert "Global Pool" in group_remarks
    assert "Solo Pool" not in group_remarks