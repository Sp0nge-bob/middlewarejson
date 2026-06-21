import copy
import json
from pathlib import Path

from app.models.rules_schema import TransformRules
from app.transformers.rules_engine import RulesTransformer

FIXTURE = Path(__file__).parent / "fixtures" / "sample_nodes.json"


def _base_rules() -> dict:
    return {
        "output": {"format": "grouped"},
        "filters": {"exclude": []},
        "tagging": {
            "rules": [
                {"match": {"remarks_equals": ["NL-WS"]}, "tag": "nl-ws"},
                {"match": {"remarks_equals": ["NL-XHTTP"]}, "tag": "nl-xhttp"},
                {"match": {"remarks_equals": ["NL-GRPC"]}, "tag": "nl-grpc"},
                {"match": {"remarks_equals": ["US-WS"]}, "tag": "us-ws"},
                {"match": {"remarks_equals": ["US-GRPC"]}, "tag": "us-grpc"},
            ],
            "default_template": "node-{index}",
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


def test_global_balancer_nl_and_us_from_different_servers() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules = TransformRules.from_dict(_base_rules())
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
    rules_data = copy.deepcopy(_base_rules())
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

    from app.models.nodes import configs_to_nodes

    nodes = configs_to_nodes(payload)
    nl_fp = nodes[0].fingerprint
    us_fp = nodes[3].fingerprint
    rules_data["balancers"][0]["members"][0]["inbound_ids"] = [nl_fp, us_fp]

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)
    ws_config = next(item for item in result if item["remarks"] == "WS Pool")
    assert set(ws_config["routing"]["balancers"][0]["selector"]) == {nl_fp, us_fp}


def test_balancer_partial_members_still_works_without_failed_suffix() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules_data = copy.deepcopy(_base_rules())
    rules_data["tagging"]["rules"] = []
    rules_data["balancers"] = [
        {
            "tag": "mixed-pool",
            "remarks": "TESTBALANCE",
            "strategy": "roundRobin",
            "members": [
                {
                    "inbound_ids": [
                        "vless|node1.example.com|ws||443||",
                        "vless|missing.example.com|ws||443||",
                    ]
                }
            ],
        }
    ]

    from app.models.nodes import configs_to_nodes

    nodes = configs_to_nodes(payload)
    rules_data["balancers"][0]["members"][0]["inbound_ids"] = [
        nodes[0].fingerprint,
        "vless|missing.example.com|ws||443||",
    ]

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)
    pool_config = next(item for item in result if item["remarks"] == "TESTBALANCE")
    assert len(pool_config["routing"]["balancers"][0]["selector"]) == 1


def test_balancer_no_members_adds_failed_suffix() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules_data = copy.deepcopy(_base_rules())
    rules_data["tagging"]["rules"] = []
    rules_data["balancers"] = [
        {
            "tag": "mixed-pool",
            "remarks": "TESTBALANCE",
            "strategy": "roundRobin",
            "members": [
                {"inbound_ids": ["vless|missing.example.com|ws||443||"]},
            ],
        }
    ]

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)
    failed_config = next(
        item for item in result if item["remarks"] == "TESTBALANCE - Failed"
    )
    assert failed_config["routing"]["balancers"][0]["selector"] == []


def test_least_ping_strategy_in_balancer_output() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules_data = copy.deepcopy(_base_rules())
    rules_data["balancers"] = [
        {
            "tag": "ping-pool",
            "remarks": "Fastest",
            "strategy": "leastPing",
            "members": [{"tags": ["nl-ws", "us-ws"]}],
        }
    ]

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)
    ping_config = next(item for item in result if item["remarks"] == "Fastest")
    assert ping_config["routing"]["balancers"][0]["strategy"] == {"type": "leastPing"}
    assert ping_config["observatory"]["subjectSelector"] == ["nl-ws", "us-ws"]
    assert ping_config["observatory"]["probeUrl"] == "https://www.google.com/generate_204"


def test_balancer_hide_members_false_keeps_standalone_profiles() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules_data = copy.deepcopy(_base_rules())
    rules_data["balancers"][0]["hide_members"] = False

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)

    remarks = [item["remarks"] for item in result]
    assert "NL+USA Balance" in remarks
    assert "NL-WS" in remarks
    assert "US-WS" in remarks
    assert "NL-XHTTP" in remarks


def test_balancer_hide_members_true_hides_member_profiles() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules_data = copy.deepcopy(_base_rules())
    rules_data["balancers"][0]["hide_members"] = True

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)

    remarks = [item["remarks"] for item in result]
    assert "NL+USA Balance" in remarks
    assert "NL-WS" not in remarks
    assert "US-WS" not in remarks
    assert "NL-XHTTP" in remarks


def test_balancer_members_can_use_remarks_match() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rules_data = copy.deepcopy(_base_rules())
    rules_data["balancers"] = [
        {
            "tag": "nl-pool",
            "remarks": "NL Pool",
            "strategy": "roundRobin",
            "members": [{"match": {"remarks_contains": ["NL-"]}}],
        }
    ]

    transformer = RulesTransformer(TransformRules.from_dict(rules_data))
    result = transformer.transform(payload)
    nl_config = next(item for item in result if item["remarks"] == "NL Pool")
    assert set(nl_config["routing"]["balancers"][0]["selector"]) == {
        "nl-ws",
        "nl-xhttp",
        "nl-grpc",
    }