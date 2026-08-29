import copy
import json
from pathlib import Path

from app.models.rules_schema import TransformRules
from app.transformers.rules_engine import RulesTransformer, member_tag_prefix


def _proxy_outbounds(config: dict) -> list[dict]:
    return [
        outbound
        for outbound in config.get("outbounds", [])
        if outbound.get("protocol") not in ("freedom", "blackhole", "dns")
        and outbound.get("tag") not in ("direct", "block")
    ]

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
    prefix = member_tag_prefix("global-pool")
    selector = global_config["routing"]["balancers"][0]["selector"]
    assert selector == [prefix]
    assert global_config["routing"]["balancers"][0]["tag"] == "balancer"

    proxies = _proxy_outbounds(global_config)
    addresses = {item["settings"]["address"] for item in proxies}
    assert addresses == {"node1.example.com", "node3.example.com"}
    assert all(item["tag"].startswith(prefix) for item in proxies)
    assert "observatory" not in global_config
    assert "burstObservatory" not in global_config

    balancer_entry = global_config["routing"]["balancers"][0]
    assert balancer_entry["strategy"] == {"type": "roundRobin"}
    assert balancer_entry["fallbackTag"].startswith(prefix)


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
    prefix = member_tag_prefix("ws-pool")
    assert ws_config["routing"]["balancers"][0]["selector"] == [prefix]
    proxies = _proxy_outbounds(ws_config)
    assert len(proxies) == 2
    assert {item["settings"]["address"] for item in proxies} == {
        "node1.example.com",
        "node3.example.com",
    }


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
    assert pool_config["routing"]["balancers"][0]["selector"] == [
        member_tag_prefix("mixed-pool")
    ]
    assert len(_proxy_outbounds(pool_config)) == 1


def test_balancer_no_members_is_skipped() -> None:
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
    remarks = [item["remarks"] for item in result]
    assert "TESTBALANCE" not in remarks
    assert "TESTBALANCE - Failed" not in remarks
    assert not any(
        "balancers" in (item.get("routing") or {})
        and item["routing"]["balancers"][0].get("selector") == []
        for item in result
        if isinstance(item.get("routing"), dict) and item["routing"].get("balancers")
    )


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
    prefix = member_tag_prefix("ping-pool")
    balancer_entry = ping_config["routing"]["balancers"][0]
    assert balancer_entry["strategy"] == {"type": "leastPing"}
    assert balancer_entry["selector"] == [prefix]
    assert balancer_entry["fallbackTag"].startswith(prefix)
    assert "observatory" not in ping_config
    assert ping_config["burstObservatory"]["subjectSelector"] == [prefix]
    assert ping_config["burstObservatory"]["pingConfig"]["destination"] == (
        "https://www.google.com/generate_204"
    )
    assert ping_config["burstObservatory"]["pingConfig"]["httpMethod"] == "HEAD"


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
    prefix = member_tag_prefix("nl-pool")
    assert nl_config["routing"]["balancers"][0]["selector"] == [prefix]
    proxies = _proxy_outbounds(nl_config)
    assert len(proxies) == 3
    assert all(item["tag"].startswith(prefix) for item in proxies)


def test_balancer_keeps_template_inbounds_and_rewrites_proxy_rule() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = RulesTransformer(TransformRules.from_dict(_base_rules())).transform(payload)
    pool = next(item for item in result if item["remarks"] == "NL+USA Balance")

    assert pool["inbounds"] == payload[0]["inbounds"]
    rules = pool["routing"]["rules"]
    assert any(rule.get("balancerTag") == "balancer" for rule in rules)
    assert not any(rule.get("outboundTag") == "proxy" for rule in rules)
    assert all("|" not in outbound.get("tag", "") for outbound in pool["outbounds"])
    assert pool["routing"]["balancers"][0]["fallbackTag"].startswith(
        member_tag_prefix("global-pool")
    )


def test_balancer_skips_loopback_members() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.append(
        {
            "remarks": "local-turn",
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "proxy",
                    "streamSettings": {"network": "ws"},
                    "settings": {"address": "127.0.0.1", "port": 9000},
                },
                {"protocol": "freedom", "tag": "direct"},
            ],
        }
    )
    rules_data = copy.deepcopy(_base_rules())
    rules_data["tagging"]["rules"] = []
    rules_data["balancers"] = [
        {
            "tag": "mixed-pool",
            "remarks": "Pool",
            "strategy": "roundRobin",
            "members": [
                {
                    "match": {
                        "address_equals": ["127.0.0.1", "node1.example.com"],
                    }
                }
            ],
        }
    ]
    result = RulesTransformer(TransformRules.from_dict(rules_data)).transform(payload)
    pool = next(item for item in result if item["remarks"] == "Pool")
    addresses = {
        outbound["settings"]["address"]
        for outbound in _proxy_outbounds(pool)
    }
    assert "127.0.0.1" not in addresses
    assert "node1.example.com" in addresses