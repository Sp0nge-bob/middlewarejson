import json
from pathlib import Path

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository, ClientRecord
from app.services.transform_service import TransformService

RAW_FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def _setup_repo(db_path: Path) -> CatalogRepository:
    repo = CatalogRepository(Database(db_path))
    nl_fp = "vless|node1.example.com|ws|/ws-path|443|tls|"
    us_fp = "vless|node5.example.com|ws|/ws-path|443|tls|"

    repo.create_balancer(
        tag="premium-pool",
        remarks="NL+USA Balance",
        strategy="roundRobin",
        member_fingerprints=[nl_fp, us_fp],
        scope="group",
        scope_target="premium",
    )
    repo.upsert_clients(
        [
            ClientRecord("client_a_sub_id12", "premium", "premium@example.com", True),
            ClientRecord("client_b_sub_id12", "basic", "basic@example.com", True),
            ClientRecord("any_sub_id_12345", "", "nogroup@example.com", True),
        ]
    )
    return repo


def test_disabled_balancer_does_not_apply(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path / "disabled.db")
    repo.set_balancer_scope("premium-pool", "disabled")

    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    service = TransformService(Settings(transform_mode="rules", db_path=str(repo._db.path)))

    result = service.transform("client_a_sub_id12", configs)
    assert "NL+USA Balance" not in [item["remarks"] for item in result]


def test_all_scope_applies_to_everyone(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path / "all.db")
    repo.set_balancer_scope("premium-pool", "all")

    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    service = TransformService(Settings(transform_mode="rules", db_path=str(repo._db.path)))

    for sub_id in ("client_a_sub_id12", "client_b_sub_id12", "any_sub_id_12345"):
        result = service.transform(sub_id, configs)
        assert "NL+USA Balance" in [item["remarks"] for item in result]


def test_client_scope_overrides_group(tmp_path: Path) -> None:
    repo = CatalogRepository(Database(tmp_path / "client.db"))
    nl_fp = "vless|node1.example.com|ws|/ws-path|443|tls|"

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
        member_fingerprints=[nl_fp],
        scope="client",
        scope_target="client_a_sub_id12",
    )
    repo.upsert_clients(
        [
            ClientRecord("client_a_sub_id12", "premium", "premium@example.com", True),
            ClientRecord("client_b_sub_id12", "premium", "basic@example.com", True),
        ]
    )

    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    service = TransformService(Settings(transform_mode="rules", db_path=str(repo._db.path)))

    solo_result = service.transform("client_a_sub_id12", configs)
    assert "Solo Pool" in [item["remarks"] for item in solo_result]

    group_result = service.transform("client_b_sub_id12", configs)
    assert "Group Pool" in [item["remarks"] for item in group_result]
    assert "Solo Pool" not in [item["remarks"] for item in group_result]