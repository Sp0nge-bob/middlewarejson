import json
from pathlib import Path

from app.models.rules_schema import TransformRules
from app.transformers.rules_engine import RulesTransformer

FIXTURE = Path(__file__).parent / "fixtures" / "raw_3xui_subscription.json"


def test_balancer_matches_hysteria_catalog_fingerprint_against_subscription() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    catalog_fp = "hysteria2|node1.example.com|hysteria||443|tls|"
    rules = TransformRules.from_dict(
        {
            "output": {"format": "grouped"},
            "balancers": [
                {
                    "tag": "hy-pool",
                    "remarks": "HY Pool",
                    "strategy": "roundRobin",
                    "hide_members": True,
                    "members": [{"inbound_ids": [catalog_fp]}],
                }
            ],
        }
    )
    result = RulesTransformer(rules).transform(payload)
    pool = next(item for item in result if item["remarks"] == "HY Pool")
    assert pool["routing"]["balancers"][0]["selector"]