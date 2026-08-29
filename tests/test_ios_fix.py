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
    assert result[0]["inbounds"][0]["tag"] == "socks"
    assert result[0]["inbounds"][0]["port"] == 10808
    assert result[0]["inbounds"][1]["protocol"] == "http"
    assert result[0]["dns"] == original[0]["dns"]
    assert result[0]["outbounds"] == original[0]["outbounds"]
    assert original[0]["inbounds"][0]["protocol"] == "mixed"


def test_apply_ios_fix_makes_3xui_autoselect_ios_safe() -> None:
    payload = {
        "remarks": "🇪🇺 Автовыбор",
        "inbounds": [
            {"port": 10808, "protocol": "mixed", "tag": "mixed"},
            {"port": 10809, "protocol": "http", "tag": "http"},
        ],
        "outbounds": [
            {"protocol": "vless", "tag": "bal-3-vless", "settings": {"address": "n1"}},
            {"protocol": "vless", "tag": "bal-3-vless-2", "settings": {"address": "n2"}},
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "balancers": [
                {
                    "tag": "balancer",
                    "selector": ["bal-3-"],
                    "strategy": {"type": "leastPing"},
                    "fallbackTag": "bal-3-vless",
                }
            ],
            "rules": [
                {"type": "field", "network": "tcp,udp", "balancerTag": "balancer"},
            ],
        },
        "burstObservatory": {
            "subjectSelector": ["bal-3-"],
            "pingConfig": {"destination": "https://www.google.com/generate_204"},
        },
        "observatory": {"subjectSelector": ["bal-3-"]},
    }
    result = apply_ios_fix(payload)
    assert result["inbounds"][0]["protocol"] == "socks"
    assert result["inbounds"][0]["tag"] == "socks"
    assert "burstObservatory" not in result
    assert "burstObservatory" not in result["routing"]
    observatory = result["observatory"]
    assert observatory["subjectSelector"] == ["bal-3-"]
    assert observatory["probeUrl"] == "https://www.gstatic.com/generate_204"
    assert observatory["probeInterval"] == "20s"
    assert observatory["enableConcurrency"] is True
    assert "observatory" not in result["routing"]
    balancer = result["routing"]["balancers"][0]
    assert balancer["tag"] == "balancer"
    assert balancer["selector"] == ["bal-3-"]
    assert balancer["strategy"] == {"type": "leastPing"}
    assert balancer["fallbackTag"] == "bal-3-vless"
    assert [item["tag"] for item in result["outbounds"]] == [
        "bal-3-vless",
        "bal-3-vless-2",
        "direct",
    ]
    assert result["routing"]["rules"][0]["balancerTag"] == "balancer"
    assert "outboundTag" not in result["routing"]["rules"][0]
    assert result["remarks"] == "🇪🇺 Автовыбор"


def test_apply_ios_fix_drops_fallback_tag_on_round_robin() -> None:
    """HAPP 4.11: roundRobin + fallbackTag without observatory →
    «core: not all dependencies are resolved» (Xray RequireFeatures)."""
    payload = {
        "remarks": "🇪🇺 Автовыбор",
        "dns": {"tag": "dns_out", "servers": ["8.8.8.8"]},
        "stats": {},
        "inbounds": [{"protocol": "socks", "tag": "socks"}],
        "outbounds": [
            {"protocol": "vless", "tag": "bal-3-vless", "settings": {"address": "n1"}},
            {"protocol": "vless", "tag": "bal-3-vless-2", "settings": {"address": "n2"}},
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "balancers": [
                {
                    "tag": "balancer",
                    "selector": ["bal-3-vless"],
                    "strategy": {"type": "roundRobin"},
                    "fallbackTag": "bal-3-vless",
                }
            ],
            "rules": [{"type": "field", "network": "tcp,udp", "balancerTag": "balancer"}],
            "observatory": {"subjectSelector": ["bal-3-vless"]},
        },
    }
    result = apply_ios_fix(payload)
    balancer = result["routing"]["balancers"][0]
    assert balancer["strategy"] == {"type": "roundRobin"}
    assert "fallbackTag" not in balancer
    assert "observatory" not in result
    assert "observatory" not in result["routing"]
    assert "burstObservatory" not in result
    assert len(result["outbounds"]) == 3
    assert result["stats"] == {}
    assert result["dns"]["tag"] == "dns_out"
    assert result["routing"]["rules"][0]["balancerTag"] == "balancer"


def test_apply_ios_fix_rewrites_3xui_burst_leastping_dump() -> None:
    """Raw 3x-ui 3.7.0 Автовыбор: leastPing + burstObservatory + google."""
    payload = {
        "remarks": "🇪🇺 Автовыбор",
        "burstObservatory": {
            "pingConfig": {
                "connectivity": "",
                "destination": "https://www.google.com/generate_204",
                "httpMethod": "HEAD",
                "interval": "1m",
                "sampling": 2,
                "timeout": "5s",
            },
            "subjectSelector": ["bal-3-"],
        },
        "dns": {"tag": "dns_out", "servers": [{"address": "8.8.8.8"}]},
        "stats": {},
        "inbounds": [
            {"port": 10808, "protocol": "mixed", "tag": "mixed"},
            {"port": 10809, "protocol": "http", "tag": "http"},
        ],
        "outbounds": [
            {"protocol": "vless", "tag": "bal-3-vless", "settings": {"address": "caelixflow.com"}},
            {"protocol": "vless", "tag": "bal-3-vless-2", "settings": {"address": "mirror2"}},
            {"protocol": "vless", "tag": "bal-3-vless-3", "settings": {"address": "mirror3"}},
            {"protocol": "vless", "tag": "bal-3-vless-4", "settings": {"address": "mirror1"}},
            {"protocol": "freedom", "tag": "direct"},
            {"protocol": "blackhole", "tag": "block"},
        ],
        "routing": {
            "balancers": [
                {
                    "fallbackTag": "bal-3-vless",
                    "selector": ["bal-3-"],
                    "strategy": {"type": "leastPing"},
                    "tag": "balancer",
                }
            ],
            "domainStrategy": "AsIs",
            "rules": [{"balancerTag": "balancer", "network": "tcp,udp", "type": "field"}],
        },
    }
    result = apply_ios_fix(payload)
    assert result["inbounds"][0]["protocol"] == "socks"
    assert "burstObservatory" not in result
    assert result["observatory"]["subjectSelector"] == ["bal-3-"]
    assert result["observatory"]["probeUrl"] == "https://www.gstatic.com/generate_204"
    assert result["observatory"]["enableConcurrency"] is True
    balancer = result["routing"]["balancers"][0]
    assert balancer["strategy"] == {"type": "leastPing"}
    assert balancer["fallbackTag"] == "bal-3-vless"
    assert balancer["selector"] == ["bal-3-"]
    assert len(result["outbounds"]) == 6
    assert result["dns"]["tag"] == "dns_out"
    assert result["stats"] == {}


def test_apply_ios_fix_keeps_leastload_with_burst() -> None:
    payload = {
        "remarks": "🇪🇺 Автовыбор",
        "burstObservatory": {
            "pingConfig": {
                "connectivity": "http://connectivitycheck.platform.hicloud.com/generate_204",
                "destination": "https://www.google.com/generate_204",
                "httpMethod": "HEAD",
                "interval": "1m",
                "sampling": 2,
                "timeout": "5s",
            },
            "subjectSelector": ["bal-3-"],
        },
        "dns": {"tag": "dns_out", "servers": ["8.8.8.8"]},
        "stats": {},
        "inbounds": [{"protocol": "mixed", "tag": "mixed"}],
        "outbounds": [
            {"protocol": "vless", "tag": "bal-3-vless", "settings": {"address": "n1"}},
            {"protocol": "vless", "tag": "bal-3-vless-2", "settings": {"address": "n2"}},
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "balancers": [
                {
                    "tag": "balancer",
                    "selector": ["bal-3-"],
                    "strategy": {
                        "type": "leastLoad",
                        "settings": {"expected": 1, "tolerance": 0.1},
                    },
                    "fallbackTag": "bal-3-vless",
                }
            ],
            "rules": [{"type": "field", "network": "tcp,udp", "balancerTag": "balancer"}],
        },
    }
    result = apply_ios_fix(payload)
    assert result["inbounds"][0]["protocol"] == "socks"
    assert "observatory" not in result
    burst = result["burstObservatory"]
    assert burst["subjectSelector"] == ["bal-3-"]
    assert burst["pingConfig"]["destination"] == "https://www.gstatic.com/generate_204"
    assert burst["pingConfig"]["connectivity"] == ""
    assert burst["pingConfig"]["interval"] == "20s"
    assert burst["pingConfig"]["sampling"] == 2
    balancer = result["routing"]["balancers"][0]
    assert balancer["strategy"]["type"] == "leastLoad"
    assert balancer["strategy"]["settings"] == {"expected": 1, "tolerance": 0.1}
    assert balancer["fallbackTag"] == "bal-3-vless"
    assert [item["tag"] for item in result["outbounds"]] == [
        "bal-3-vless",
        "bal-3-vless-2",
        "direct",
    ]
    assert result["stats"] == {}
    assert result["dns"]["tag"] == "dns_out"


def test_apply_ios_fix_keeps_random_drops_fallback() -> None:
    payload = {
        "inbounds": [{"protocol": "socks", "tag": "socks"}],
        "outbounds": [{"protocol": "vless", "tag": "bal-3-vless"}],
        "routing": {
            "balancers": [
                {
                    "tag": "balancer",
                    "selector": ["bal-3-"],
                    "strategy": {"type": "random"},
                    "fallbackTag": "bal-3-vless",
                }
            ]
        },
        "burstObservatory": {"subjectSelector": ["bal-3-"]},
    }
    result = apply_ios_fix(payload)
    assert result["routing"]["balancers"][0]["strategy"] == {"type": "random"}
    assert "fallbackTag" not in result["routing"]["balancers"][0]
    assert "observatory" not in result
    assert "burstObservatory" not in result


def test_apply_ios_fix_fills_missing_leastping_fallback() -> None:
    payload = {
        "inbounds": [{"protocol": "socks", "tag": "socks"}],
        "outbounds": [
            {"protocol": "vless", "tag": "bal-3-vless", "settings": {"address": "n1"}},
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "balancers": [
                {
                    "tag": "balancer",
                    "selector": ["bal-3-"],
                    "strategy": {"type": "leastPing"},
                }
            ]
        },
    }
    result = apply_ios_fix(payload)
    assert result["routing"]["balancers"][0]["fallbackTag"] == "bal-3-vless"
    assert result["observatory"]["subjectSelector"] == ["bal-3-"]


def test_apply_ios_fix_leaves_stats_and_dns_on_ordinary_proxy() -> None:
    payload = {
        "remarks": "NL",
        "dns": {"tag": "dns_out", "servers": ["8.8.8.8"]},
        "stats": {},
        "policy": {
            "system": {
                "statsOutboundUplink": True,
                "statsOutboundDownlink": True,
            }
        },
        "inbounds": [{"protocol": "socks", "tag": "socks"}],
        "outbounds": [{"protocol": "vless", "tag": "proxy"}],
        "routing": {"rules": [{"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}]},
    }
    result = apply_ios_fix(payload)
    assert result["stats"] == {}
    assert result["dns"]["tag"] == "dns_out"
    assert result["dns"]["servers"] == ["8.8.8.8"]
    system = (result.get("policy") or {}).get("system") or {}
    assert system.get("statsOutboundUplink") is True
    assert result["routing"]["rules"][0]["outboundTag"] == "proxy"


def test_apply_ios_fix_strips_fakedns_and_nested_tls() -> None:
    payload = {
        "remarks": "NL",
        "inbounds": [
            {
                "protocol": "socks",
                "tag": "mixed",
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic", "fakedns"]},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "tag": "proxy",
                "streamSettings": {
                    "network": "ws",
                    "security": "tls",
                    "tlsSettings": {
                        "fingerprint": "random",
                        "settings": {"verifyPeerCertByName": "0"},
                    },
                    "wsSettings": {"path": "/ws", "heartbeatPeriod": 0},
                },
            }
        ],
    }
    result = apply_ios_fix(payload)
    assert result["inbounds"][0]["tag"] == "socks"
    assert "fakedns" not in result["inbounds"][0]["sniffing"]["destOverride"]
    tls = result["outbounds"][0]["streamSettings"]["tlsSettings"]
    assert "settings" not in tls
    assert tls["fingerprint"] == "random"
    assert "heartbeatPeriod" not in result["outbounds"][0]["streamSettings"]["wsSettings"]


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
