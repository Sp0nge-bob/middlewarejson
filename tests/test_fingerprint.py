import json
from pathlib import Path

from app.models.inbound import InboundDescriptor, compute_inbound_fingerprint
from app.models.nodes import configs_to_nodes

RAW_FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_all_inbounds_have_unique_fingerprints() -> None:
    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    fingerprints = [
        descriptor.fingerprint
        for index, config in enumerate(configs)
        if (descriptor := InboundDescriptor.from_config(index, config)) is not None
    ]
    assert len(fingerprints) == 10
    assert len(set(fingerprints)) == 10


def test_fingerprint_format_for_nl_ws() -> None:
    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    outbound = configs[0]["outbounds"][0]
    assert compute_inbound_fingerprint(outbound) == (
        "vless|node1.example.com|ws|/ws-path|443|tls|"
    )


def test_nodes_receive_fingerprint() -> None:
    configs = json.loads(RAW_FIXTURE.read_text(encoding="utf-8"))
    nodes = configs_to_nodes(configs)
    assert len(nodes) == 10
    assert all(node.fingerprint for node in nodes)
    assert len({node.fingerprint for node in nodes}) == 10