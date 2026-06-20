import re

from app.db.repository import CatalogRepository
from app.models.rules_schema import (
    BalancerMember,
    BalancerRule,
    OutputConfig,
    TransformRules,
)


def _slugify_tag(value: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    cleaned = re.sub(r"[\s_]+", "-", cleaned.strip().lower())
    return cleaned or "balancer"


def build_balancer_rules(
    repository: CatalogRepository,
    balancer_tag: str,
) -> TransformRules | None:
    balancer = repository.get_balancer_by_tag(balancer_tag)
    if balancer is None or not balancer.member_fingerprints:
        return None

    return TransformRules(
        output=OutputConfig(format="grouped"),
        balancers=[
            BalancerRule(
                tag=balancer.tag,
                remarks=balancer.remarks or balancer.tag,
                strategy=balancer.strategy,  # type: ignore[arg-type]
                members=[
                    BalancerMember(inbound_ids=balancer.member_fingerprints),
                ],
            )
        ],
    )


def default_balancer_tag(name: str) -> str:
    return _slugify_tag(name)