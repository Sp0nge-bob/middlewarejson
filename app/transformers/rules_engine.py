import copy
import re
from typing import Any

from app.models.nodes import ProxyNode, configs_to_nodes
from app.models.rules_schema import BalancerRule, TaggingRule, TransformRules
from app.models.subscription import SubscriptionPayload
from app.services.matching import node_matches
from app.services.transformer import SubscriptionTransformer

_STRATEGY_MAP = {
    "roundRobin": "roundRobin",
    "leastLoad": "leastLoad",
    "random": "random",
}


def _as_config_list(payload: SubscriptionPayload) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    return [payload]


def _apply_tagging(rules: TransformRules, nodes: list[ProxyNode]) -> list[ProxyNode]:
    tagged: list[ProxyNode] = []
    used_tags: set[str] = set()

    for node in nodes:
        tag = _resolve_tag(rules.tagging.rules, node, used_tags, rules.tagging.default_template)
        used_tags.add(tag)
        tagged.append(node.with_tag(tag))

    return tagged


def _resolve_tag(
    tagging_rules: list[TaggingRule],
    node: ProxyNode,
    used_tags: set[str],
    default_template: str,
) -> str:
    for rule in tagging_rules:
        if node_matches(node, rule.match):
            return _ensure_unique(rule.tag, used_tags)

    if node.fingerprint:
        return _ensure_unique(node.fingerprint, used_tags)

    base = default_template.format(
        index=node.source_index,
        remarks=node.remarks,
        protocol=node.protocol,
        network=node.network or "default",
        slug=_slugify(node.remarks),
    )
    return _ensure_unique(base, used_tags)


def _ensure_unique(tag: str, used_tags: set[str]) -> str:
    if tag not in used_tags:
        return tag
    counter = 2
    while f"{tag}-{counter}" in used_tags:
        counter += 1
    return f"{tag}-{counter}"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    cleaned = re.sub(r"[\s_]+", "-", cleaned.strip().lower())
    return cleaned or "node"


def _filter_nodes(rules: TransformRules, nodes: list[ProxyNode]) -> list[ProxyNode]:
    if not rules.filters.exclude:
        return nodes
    return [
        node
        for node in nodes
        if not any(node_matches(node, exclude_rule) for exclude_rule in rules.filters.exclude)
    ]


def _resolve_balancer_members(balancer: BalancerRule, nodes: list[ProxyNode]) -> list[str]:
    tags: list[str] = []
    tag_set: set[str] = set()
    nodes_by_tag = {node.tag: node for node in nodes}

    nodes_by_fingerprint = {node.fingerprint: node for node in nodes if node.fingerprint}

    for member in balancer.members:
        for inbound_id in member.inbound_ids:
            node = nodes_by_fingerprint.get(inbound_id)
            if node is not None and node.tag not in tag_set:
                tags.append(node.tag)
                tag_set.add(node.tag)

        for explicit_tag in member.tags:
            if explicit_tag in nodes_by_tag and explicit_tag not in tag_set:
                tags.append(explicit_tag)
                tag_set.add(explicit_tag)

        if member.match is not None:
            for node in nodes:
                if node_matches(node, member.match) and node.tag not in tag_set:
                    tags.append(node.tag)
                    tag_set.add(node.tag)

    return tags


def _node_balancer_map(
    rules: TransformRules, nodes: list[ProxyNode]
) -> dict[str, BalancerRule]:
    mapping: dict[str, BalancerRule] = {}
    for balancer in rules.balancers:
        for tag in _resolve_balancer_members(balancer, nodes):
            mapping[tag] = balancer
    return mapping


def _system_outbounds(template_config: dict[str, Any]) -> list[dict[str, Any]]:
    outbounds = template_config.get("outbounds", [])
    if not isinstance(outbounds, list):
        return []
    system: list[dict[str, Any]] = []
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        protocol = outbound.get("protocol", "")
        tag = outbound.get("tag", "")
        if protocol in ("freedom", "blackhole") or tag in ("direct", "block"):
            system.append(copy.deepcopy(outbound))
    return system


def _build_balancer_config(
    template_config: dict[str, Any],
    nodes: list[ProxyNode],
    balancer: BalancerRule,
) -> dict[str, Any]:
    config = copy.deepcopy(template_config)
    proxy_outbounds = [copy.deepcopy(node.outbound) for node in nodes]
    config["outbounds"] = proxy_outbounds + _system_outbounds(template_config)
    config["remarks"] = balancer.remarks or balancer.tag

    routing: dict[str, Any] = {}
    selector = [node.tag for node in nodes]
    routing["balancers"] = [
        {
            "tag": balancer.tag,
            "selector": selector,
            "strategy": {"type": _STRATEGY_MAP.get(balancer.strategy, "roundRobin")},
        }
    ]
    routing["domainStrategy"] = "AsIs"
    routing["rules"] = [
        {
            "type": "field",
            "network": "tcp,udp",
            "balancerTag": balancer.tag,
        }
    ]
    config["routing"] = routing
    return config


def _build_grouped_output(
    configs: list[dict[str, Any]],
    nodes: list[ProxyNode],
    rules: TransformRules,
) -> list[dict[str, Any]]:
    nodes_by_index = {node.source_index: node for node in nodes}
    balancer_for_tag = _node_balancer_map(rules, nodes)
    emitted_balancers: set[str] = set()
    balancer_nodes: dict[str, list[ProxyNode]] = {}

    for node in nodes:
        balancer = balancer_for_tag.get(node.tag)
        if balancer is None:
            continue
        balancer_nodes.setdefault(balancer.tag, []).append(node)

    result: list[dict[str, Any]] = []
    for index, config in enumerate(configs):
        node = nodes_by_index.get(index)
        if node is None:
            result.append(copy.deepcopy(config))
            continue

        balancer = balancer_for_tag.get(node.tag)
        if balancer is None:
            result.append(copy.deepcopy(config))
            continue

        if balancer.tag in emitted_balancers:
            continue

        pool_nodes = balancer_nodes.get(balancer.tag, [])
        if not pool_nodes:
            continue

        template = configs[pool_nodes[0].source_index]
        result.append(_build_balancer_config(template, pool_nodes, balancer))
        emitted_balancers.add(balancer.tag)

    return result


def _build_single_merged_config(
    template_config: dict[str, Any],
    nodes: list[ProxyNode],
    rules: TransformRules,
) -> dict[str, Any]:
    config = copy.deepcopy(template_config)
    proxy_outbounds = [copy.deepcopy(node.outbound) for node in nodes]
    config["outbounds"] = proxy_outbounds + _system_outbounds(template_config)
    config["remarks"] = rules.output.remarks

    balancers_json: list[dict[str, Any]] = []
    for balancer in rules.balancers:
        selector = _resolve_balancer_members(balancer, nodes)
        if not selector:
            continue
        balancers_json.append(
            {
                "tag": balancer.tag,
                "selector": selector,
                "strategy": {"type": _STRATEGY_MAP.get(balancer.strategy, "roundRobin")},
            }
        )

    default_balancer = rules.output.default_balancer or (
        balancers_json[0]["tag"] if balancers_json else ""
    )
    routing: dict[str, Any] = {"domainStrategy": "AsIs", "balancers": balancers_json}
    if default_balancer:
        routing["rules"] = [
            {"type": "field", "network": "tcp,udp", "balancerTag": default_balancer}
        ]
    config["routing"] = routing
    return config


class RulesTransformer(SubscriptionTransformer):
    def __init__(self, rules: TransformRules) -> None:
        self._rules = rules

    def transform(self, payload: SubscriptionPayload) -> SubscriptionPayload:
        if self._rules.output.format == "passthrough":
            return payload

        configs = _as_config_list(payload)
        if not configs:
            return payload

        nodes = configs_to_nodes(configs)
        nodes = _filter_nodes(self._rules, nodes)
        nodes = _apply_tagging(self._rules, nodes)

        if not nodes:
            return payload

        output_format = self._rules.output.format

        if output_format == "grouped":
            return _build_grouped_output(configs, nodes, self._rules)

        if output_format == "array":
            return [
                _build_balancer_config(configs[node.source_index], [node], self._rules.balancers[0])
                for node in nodes
            ]

        return _build_single_merged_config(configs[0], nodes, self._rules)