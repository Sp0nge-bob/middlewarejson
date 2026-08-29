import copy
import json
from pathlib import Path

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository, ClientRecord
from app.services.panel_api import normalize_transform_mode
from app.services.transform_service import TransformService
from app.transformers.ios_fix import apply_ios_fix

RAW = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_normalize_accepts_ios_fix_aliases() -> None:
    assert normalize_transform_mode("IOS-FIX") == "ios-fix"
    assert normalize_transform_mode("ios_fix") == "ios-fix"
    assert normalize_transform_mode("iosfix") == "ios-fix"


def test_apply_ios_fix_changes_only_first_mixed() -> None:
    payload = [
        {
            "remarks": "A",
            "dns": {"servers": ["8.8.8.8"]},
            "inbounds": [
                {
                    "port": 10808,
                    "protocol": "mixed",
                    "tag": "mixed",
                    "settings": {"auth": "noauth", "udp": True},
                },
                {"port": 10809, "protocol": "http", "tag": "http"},
            ],
            "outbounds": [
                {"protocol": "vless", "tag": "proxy", "settings": {"address": "n1", "port": 443}}
            ],
        }
    ]
    original = copy.deepcopy(payload)
    result = apply_ios_fix(payload)

    assert result[0]["inbounds"][0]["protocol"] == "socks"
    assert result[0]["inbounds"][0]["tag"] == "mixed"
    assert result[0]["inbounds"][0]["port"] == 10808
    assert result[0]["inbounds"][1]["protocol"] == "http"
    assert result[0]["dns"] == original[0]["dns"]
    assert result[0]["outbounds"] == original[0]["outbounds"]
    assert original[0]["inbounds"][0]["protocol"] == "mixed"


def test_apply_ios_fix_leaves_socks_first_unchanged() -> None:
    payload = {
        "remarks": "ok",
        "inbounds": [{"protocol": "socks", "port": 10808}],
        "outbounds": [{"protocol": "vless", "tag": "proxy"}],
    }
    result = apply_ios_fix(payload)
    assert result["inbounds"][0]["protocol"] == "socks"


def test_ios_fix_mode_does_not_drop_loopback_or_apply_balancers(tmp_path: Path) -> None:
    repo = CatalogRepository(Database(tmp_path / "ios.db"))
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
    repo.set_setting("transform_mode", "ios-fix")

    configs = json.loads(RAW.read_text(encoding="utf-8"))
    service = TransformService(Settings(transform_mode="passthrough", db_path=str(repo._db.path)))
    result = service.transform("client_a_sub_id12", configs)
    remarks = [item["remarks"] for item in result]
    assert "Pool" not in remarks
    assert "hysteria-turn" in remarks
    assert "NL-WS" in remarks
