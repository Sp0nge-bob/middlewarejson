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
    balancer_tags: list[str] | str,
) -> TransformRules | None:
    if isinstance(balancer_tags, str):
        balancer_tags = [balancer_tags]

    balancers: list[BalancerRule] = []
    for balancer_tag in balancer_tags:
        balancer = repository.get_balancer_by_tag(balancer_tag)
        if balancer is None or not balancer.member_fingerprints:
            continue
        balancers.append(
            BalancerRule(
                tag=balancer.tag,
                remarks=balancer.remarks or balancer.tag,
                strategy=balancer.strategy,  # type: ignore[arg-type]
                hide_members=balancer.hide_members,
                members=[
                    BalancerMember(inbound_ids=balancer.member_fingerprints),
                ],
            )
        )

    if not balancers:
        return None

    return TransformRules(
        output=OutputConfig(format="grouped"),
        balancers=balancers,
    )


def default_balancer_tag(name: str) -> str:
    return _slugify_tag(name)