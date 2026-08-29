import json
from pathlib import Path

from app.models.rules_schema import TransformRules
from app.transformers.client_compat import normalize_for_client
from app.transformers.rules_engine import RulesTransformer, member_tag_prefix

RAW = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"
SAMPLE_NODES = Path(__file__).parent / "fixtures" / "sample_nodes.json"


def test_drops_loopback_profiles() -> None:
    payload = json.loads(RAW.read_text(encoding="utf-8"))
    result = normalize_for_client(payload)
    remarks = [item["remarks"] for item in result]
    assert "hysteria-turn" not in remarks
    assert "NL-WS" in remarks


def test_strips_fakedns_and_puts_socks_first() -> None:
    payload = [
        {
            "remarks": "node",
            "inbounds": [
                {
                    "port": 10808,
                    "protocol": "mixed",
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls", "quic", "fakedns"],
                    },
                    "tag": "mixed",
                },
                {"port": 10809, "protocol": "http", "tag": "http"},
            ],
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "proxy",
                    "settings": {"address": "node.example.com", "port": 443},
                }
            ],
        }
    ]
    result = normalize_for_client(payload)
    inbounds = result[0]["inbounds"]
    assert inbounds[0]["protocol"] == "socks"
    assert inbounds[0]["listen"] == "127.0.0.1"
    mixed = next(item for item in inbounds if item["protocol"] == "mixed")
    assert "fakedns" not in mixed["sniffing"]["destOverride"]


def test_flattens_tls_and_strips_server_only_xhttp_fields() -> None:
    payload = [
        {
            "remarks": "xhttp",
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "proxy",
                    "settings": {"address": "cdn.example.com", "port": 443},
                    "streamSettings": {
                        "network": "xhttp",
                        "security": "tls",
                        "sockopt": {"dialerProxy": "frag"},
                        "externalProxy": [{"dest": "hidden"}],
                        "tlsSettings": {
                            "serverName": "cdn.example.com",
                            "settings": {"fingerprint": "firefox"},
                        },
                        "xhttpSettings": {
                            "path": "/xhttp",
                            "mode": "auto",
                            "noSSEHeader": True,
                            "scMaxBufferedPosts": 30,
                            "scMaxEachPostBytes": "1000000",
                            "scMinPostsIntervalMs": "30",
                        },
                    },
                }
            ],
        }
    ]
    result = normalize_for_client(payload)
    stream = result[0]["outbounds"][0]["streamSettings"]
    assert "sockopt" not in stream
    assert "externalProxy" not in stream
    assert stream["tlsSettings"]["fingerprint"] == "firefox"
    assert "settings" not in stream["tlsSettings"]
    xhttp = stream["xhttpSettings"]
    assert "noSSEHeader" not in xhttp
    assert "scMaxBufferedPosts" not in xhttp
    assert "scMaxEachPostBytes" not in xhttp


def test_drops_dead_balancer_profile() -> None:
    payload = [
        {
            "remarks": "dead",
            "outbounds": [{"protocol": "freedom", "tag": "direct"}],
            "routing": {
                "balancers": [{"tag": "balancer", "selector": [], "strategy": {"type": "roundRobin"}}],
                "rules": [{"type": "field", "network": "tcp,udp", "balancerTag": "balancer"}],
            },
        },
        {
            "remarks": "ok",
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "proxy",
                    "settings": {"address": "node.example.com", "port": 443},
                }
            ],
        },
    ]
    result = normalize_for_client(payload)
    assert [item["remarks"] for item in result] == ["ok"]


def test_drops_localhost_dns_servers() -> None:
    payload = [
        {
            "remarks": "dns",
            "dns": {"servers": [{"address": "localhost", "domains": ["geosite:cn"]}, "1.1.1.1"]},
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "proxy",
                    "settings": {"address": "node.example.com", "port": 443},
                }
            ],
        }
    ]
    result = normalize_for_client(payload)
    assert result[0]["dns"]["servers"] == ["1.1.1.1"]


def test_balancer_profile_stays_connectable_after_compat() -> None:
    payload = json.loads(SAMPLE_NODES.read_text(encoding="utf-8"))
    rules = TransformRules.from_dict(
        {
            "output": {"format": "grouped"},
            "tagging": {
                "rules": [
                    {"match": {"remarks_equals": ["NL-WS"]}, "tag": "nl-ws"},
                    {"match": {"remarks_equals": ["US-WS"]}, "tag": "us-ws"},
                ]
            },
            "balancers": [
                {
                    "tag": "global-pool",
                    "remarks": "NL+USA Balance",
                    "strategy": "roundRobin",
                    "members": [{"tags": ["nl-ws", "us-ws"]}],
                }
            ],
        }
    )
    transformed = RulesTransformer(rules).transform(payload)
    result = normalize_for_client(transformed)
    pool = next(item for item in result if item["remarks"] == "NL+USA Balance")
    prefix = member_tag_prefix("global-pool")
    assert pool["routing"]["balancers"][0]["selector"] == [prefix]
    assert pool["routing"]["balancers"][0]["fallbackTag"].startswith(prefix)
    assert pool["inbounds"][0]["protocol"] == "socks"
    assert pool["outbounds"][0]["protocol"] not in ("freedom", "blackhole")
