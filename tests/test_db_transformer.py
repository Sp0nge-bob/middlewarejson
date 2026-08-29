import json
from pathlib import Path

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository, ClientRecord
from app.services.transform_service import TransformService

RAW_FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_group_balancer_applies_only_to_assigned_group(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    repo = CatalogRepository(Database(db_path))
    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))

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
            ClientRecord(
                sub_id="client_a_sub_id12",
                group_name="premium",
                email="premium@example.com",
                enable=True,
            ),
            ClientRecord(
                sub_id="client_b_sub_id12",
                group_name="basic",
                email="basic@example.com",
                enable=True,
            ),
            ClientRecord(
                sub_id="any_sub_id_12345",
                group_name="",
                email="nogroup@example.com",
                enable=True,
            ),
        ]
    )
    settings = Settings(
        transform_mode="rules",
        db_path=str(db_path),
    )
    service = TransformService(settings)

    premium_result = service.transform("client_a_sub_id12", configs)
    assert isinstance(premium_result, list)
    premium_remarks = [item["remarks"] for item in premium_result]
    assert "NL+USA Balance" in premium_remarks

    global_config = next(
        item for item in premium_result if item["remarks"] == "NL+USA Balance"
    )
    selector = global_config["routing"]["balancers"][0]["selector"]
    assert selector == ["bal-premium-pool-"]
    assert global_config["routing"]["balancers"][0]["tag"] == "balancer"
    proxies = [
        outbound
        for outbound in global_config["outbounds"]
        if outbound.get("tag") not in ("direct", "block")
        and outbound.get("protocol") not in ("freedom", "blackhole", "dns")
    ]
    assert len(proxies) == 2
    assert {item["settings"]["address"] for item in proxies} == {
        "node1.example.com",
        "node5.example.com",
    }

    for sub_id in ("client_b_sub_id12", "any_sub_id_12345"):
        result = service.transform(sub_id, configs)
        remarks = [item["remarks"] for item in result]
        assert "NL+USA Balance" not in remarks
        loopback_dropped = sum(
            1
            for item in configs
            if any(
                str((outbound.get("settings") or {}).get("address", "")).startswith("127.")
                for outbound in item.get("outbounds", [])
                if outbound.get("protocol") not in ("freedom", "blackhole", "dns")
            )
        )
        assert len(result) == len(configs) - loopback_dropped