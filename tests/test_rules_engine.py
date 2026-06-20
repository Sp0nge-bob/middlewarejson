import json
from pathlib import Path

import yaml

from app.models.rules_schema import TransformRules
from app.services.rules_loader import load_rules
from app.transformers.rules_engine import RulesTransformer

FIXTURE = Path(__file__).parent / "fixtures" / "sample_nodes.json"
RULES = Path(__file__).parent.parent / "config" / "rules.yaml"


def test_global_balancer_nl_and_us_from_different_servers() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules = load_rules(RULES)
    result = RulesTransformer(rules).transform(payload)

    assert isinstance(result, list)
    remarks = [item["remarks"] for item in result]
    assert "NL+USA Balance" in remarks
    assert "NL-XHTTP" in remarks
    assert "hysteria" in remarks

    global_config = next(item for item in result if item["remarks"] == "NL+USA Balance")
    selector = global_config["routing"]["balancers"][0]["selector"]
    assert selector == ["nl-ws", "us-ws"]

    outbounds_by_tag = {o["tag"]: o for o in global_config["outbounds"]}
    assert outbounds_by_tag["nl-ws"]["settings"]["address"] == "node1.example.com"
    assert outbounds_by_tag["us-ws"]["settings"]["address"] == "node3.example.com"
    assert outbounds_by_tag["nl-ws"]["settings"]["address"] != outbounds_by_tag["us-ws"]["settings"]["address"]

    assert global_config["routing"]["balancers"][0]["strategy"] == {"type": "roundRobin"}


def test_balancer_members_can_use_inbound_ids() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules_data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    rules_data["tagging"]["rules"] = []
    rules_data["balancers"] = [
        {
            "tag": "ws-pool",
            "remarks": "WS Pool",
            "strategy": "roundRobin",
            "members": [
                {
                    "inbound_ids": [
                        "vless|node1.example.com|ws||443||",
                        "vless|node3.example.com|ws||443||",
                    ]
                }
            ],
        }
    ]
    rules_data["output"]["format"] = "grouped"

    from app.models.nodes import configs_to_nodes

    nodes = configs_to_nodes(payload)
    nl_fp = nodes[0].fingerprint
    us_fp = nodes[3].fingerprint
    rules_data["balancers"][0]["members"][0]["inbound_ids"] = [nl_fp, us_fp]

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)
    ws_config = next(item for item in result if item["remarks"] == "WS Pool")
    assert set(ws_config["routing"]["balancers"][0]["selector"]) == {nl_fp, us_fp}


def test_balancer_members_can_use_remarks_match() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules_data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    rules_data["balancers"] = [
        {
            "tag": "nl-pool",
            "remarks": "NL Pool",
            "strategy": "roundRobin",
            "members": [{"match": {"remarks_contains": ["NL-"]}}],
        }
    ]
    rules_data["output"]["format"] = "grouped"

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)
    nl_config = next(item for item in result if item["remarks"] == "NL Pool")
    assert set(nl_config["routing"]["balancers"][0]["selector"]) == {
        "nl-ws",
        "nl-xhttp",
        "nl-grpc",
    }