import json
from pathlib import Path

from app.transformers.happ_sanitize import sanitize_for_happ

FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_drops_localhost_hysteria_turn() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = sanitize_for_happ(payload)
    remarks = [item["remarks"] for item in result]
    assert "hysteria-turn" not in remarks


def test_converts_hysteria_to_hysteria2() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = sanitize_for_happ(payload)
    hy_config = next(item for item in result if item["remarks"] == "hysteria")
    proxy = next(o for o in hy_config["outbounds"] if o.get("tag") == "proxy")
    assert proxy["protocol"] == "hysteria2"
    server = proxy["settings"]["servers"][0]
    assert server["address"] == "node1.example.com"
    assert server["password"] == "test-auth-token"
    assert proxy["settings"]["obfs"]["salamander"]["password"] == "obfs-pass"
    assert "finalmask" not in proxy.get("streamSettings", {})


def test_normalizes_xhttp_padding_range() -> None:
    payload = [
        {
            "remarks": "xhttp-padding",
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "proxy",
                    "streamSettings": {
                        "network": "xhttp",
                        "security": "tls",
                        "xhttpSettings": {"path": "/xhttp", "mode": "auto", "xPaddingBytes": "100-1000"},
                        "tlsSettings": {"fingerprint": "firefox", "settings": {"fingerprint": "firefox"}},
                    },
                    "settings": {
                        "address": "node1.example.com",
                        "port": 443,
                        "id": "11111111-1111-1111-1111-111111111111",
                    },
                }
            ],
        }
    ]
    result = sanitize_for_happ(payload)
    proxy = result[0]["outbounds"][0]
    assert proxy["streamSettings"]["xhttpSettings"]["xPaddingBytes"] == 100
    assert "settings" not in proxy["streamSettings"]["tlsSettings"]


def test_strips_3xui_boilerplate_for_happ() -> None:
    payload = [
        {
            "remarks": "plain",
            "inbounds": [{"port": 10808, "protocol": "mixed", "tag": "mixed"}],
            "dns": {"servers": [{"address": "8.8.8.8"}]},
            "policy": {"levels": {"8": {"connIdle": 300}}},
            "stats": {},
            "log": {"loglevel": "warning"},
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "proxy",
                    "streamSettings": {"network": "ws", "security": "tls"},
                    "settings": {
                        "address": "node1.example.com",
                        "port": 443,
                        "id": "11111111-1111-1111-1111-111111111111",
                    },
                }
            ],
        }
    ]
    result = sanitize_for_happ(payload)
    config = result[0]
    assert "inbounds" not in config
    assert "dns" not in config
    assert "policy" not in config
    assert "stats" not in config
    assert "log" not in config


def test_strips_reality_mldsa_fields() -> None:
    payload = [
        {
            "remarks": "reality",
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "proxy",
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "serverName": "www.intel.com",
                            "publicKey": "abc",
                            "shortId": "fc8311ba",
                            "mldsa65Verify": "",
                            "settings": {"mldsa65Verify": ""},
                        },
                    },
                    "settings": {
                        "address": "usa.example.com",
                        "port": 443,
                        "id": "11111111-1111-1111-1111-111111111111",
                    },
                }
            ],
        }
    ]
    result = sanitize_for_happ(payload)
    reality = result[0]["outbounds"][0]["streamSettings"]["realitySettings"]
    assert "mldsa65Verify" not in reality
    assert "mldsa65Verify" not in reality.get("settings", {})