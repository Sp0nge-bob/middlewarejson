import json
from pathlib import Path

from app.models.inbound import InboundDescriptor, compute_inbound_fingerprint
from app.models.panel_inbound import panel_inbounds_to_descriptors

PANEL_FIXTURE = Path(__file__).parent / "fixtures" / "panel_inbounds_list.json"
SUB_FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_panel_projection_matches_subscription_fingerprints() -> None:
    panel_inbounds = json.loads(PANEL_FIXTURE.read_text(encoding="utf-8"))
    subscription_configs = json.loads(SUB_FIXTURE.read_text(encoding="utf-8"))

    panel_fps = {descriptor.fingerprint for descriptor in panel_inbounds_to_descriptors(panel_inbounds)}
    sub_fps = {
        descriptor.fingerprint
        for index, config in enumerate(subscription_configs)
        if (descriptor := InboundDescriptor.from_config(index, config)) is not None
    }

    assert len(panel_fps) == 10
    assert panel_fps == sub_fps


def test_panel_projection_preserves_panel_ids() -> None:
    panel_inbounds = json.loads(PANEL_FIXTURE.read_text(encoding="utf-8"))
    descriptors = panel_inbounds_to_descriptors(panel_inbounds)

    assert len(descriptors) == 10
    assert {descriptor.panel_inbound_id for descriptor in descriptors} == set(range(1, 11))


def test_external_proxy_expands_to_multiple_endpoints() -> None:
    inbound = {
        "id": 99,
        "remark": "multi-proxy",
        "protocol": "vless",
        "port": 443,
        "shareAddr": "primary.example.com",
        "enable": True,
        "streamSettings": {
            "network": "ws",
            "security": "tls",
            "wsSettings": {"path": "/path"},
            "externalProxy": [
                {"dest": "relay1.example.com", "port": 443, "forceTls": "same"},
                {"dest": "relay2.example.com", "port": 8443, "forceTls": "tls"},
            ],
        },
    }

    descriptors = panel_inbounds_to_descriptors([inbound])
    assert len(descriptors) == 2
    assert descriptors[0].panel_inbound_id == 99
    assert descriptors[0].endpoint_index == 0
    assert descriptors[1].endpoint_index == 1
    assert descriptors[0].address == "relay1.example.com"
    assert descriptors[1].address == "relay2.example.com"
    assert descriptors[0].fingerprint != descriptors[1].fingerprint


def test_disabled_inbound_is_skipped() -> None:
    inbound = {
        "id": 100,
        "remark": "off",
        "protocol": "vless",
        "port": 443,
        "shareAddr": "off.example.com",
        "enable": False,
        "streamSettings": {"network": "tcp", "security": "none"},
    }
    assert panel_inbounds_to_descriptors([inbound]) == []


def test_fingerprint_format_unchanged() -> None:
    outbound = {
        "protocol": "vless",
        "settings": {"address": "node1.example.com", "port": 443},
        "streamSettings": {
            "network": "ws",
            "security": "tls",
            "wsSettings": {"path": "/ws-path"},
        },
    }
    assert compute_inbound_fingerprint(outbound) == (
        "vless|node1.example.com|ws|/ws-path|443|tls|"
    )