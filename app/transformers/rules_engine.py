import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

from app.models.inbound import fingerprint_match_keys
from app.models.nodes import ProxyNode, configs_to_nodes
from app.models.rules_schema import BalancerRule, TaggingRule, TransformRules
from app.models.subscription import SubscriptionPayload
from app.services.matching import node_matches
from app.services.transformer import SubscriptionTransformer

_STRATEGY_MAP = {
    "roundRobin": "roundRobin",
    "leastLoad": "leastLoad",
    "leastPing": "leastPing",
    "random": "random",
}

_OBSERVATORY_STRATEGIES = frozenset({"leastPing", "leastLoad"})

_XRAY_BALANCER_TAG = "balancer"
_LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "localhost", "::1"})
_PROBE_URL = "https://www.google.com/generate_204"


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


def _find_node_by_fingerprint(
    inbound_id: str,
    nodes_by_fingerprint: dict[str, ProxyNode],
) -> ProxyNode | None:
    for key in fingerprint_match_keys(inbound_id):
        node = nodes_by_fingerprint.get(key)
        if node is not None:
            return node
    return None


def _resolve_balancer_members(balancer: BalancerRule, nodes: list[ProxyNode]) -> list[str]:
    tags: list[str] = []
    tag_set: set[str] = set()
    nodes_by_tag = {node.tag: node for node in nodes}

    nodes_by_fingerprint = {node.fingerprint: node for node in nodes if node.fingerprint}

    for member in balancer.members:
        for inbound_id in member.inbound_ids:
            node = _find_node_by_fingerprint(inbound_id, nodes_by_fingerprint)
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


def _expected_balancer_fingerprints(balancer: BalancerRule) -> list[str]:
    fingerprints: list[str] = []
    seen: set[str] = set()
    for member in balancer.members:
        for inbound_id in member.inbound_ids:
            if inbound_id not in seen:
                seen.add(inbound_id)
                fingerprints.append(inbound_id)
    return fingerprints


def _balancer_members_incomplete(balancer: BalancerRule, nodes: list[ProxyNode]) -> bool:
    return len(_resolve_balancer_members(balancer, nodes)) == 0


def _log_balancer_resolution(balancer: BalancerRule, nodes: list[ProxyNode]) -> None:
    expected = _expected_balancer_fingerprints(balancer)
    if not expected:
        return
    resolved = _resolve_balancer_members(balancer, nodes)
    if resolved:
        return
    nodes_by_fingerprint = {node.fingerprint: node for node in nodes if node.fingerprint}
    missing = [
        fingerprint
        for fingerprint in expected
        if _find_node_by_fingerprint(fingerprint, nodes_by_fingerprint) is None
    ]
    available = sorted(nodes_by_fingerprint.keys())
    logger.warning(
        "balancer %s: 0/%s members matched for sub; missing=%s; available=%s",
        balancer.tag,
        len(expected),
        missing,
        available[:8],
    )


def _node_address(node: ProxyNode) -> str:
    settings = node.outbound.get("settings", {})
    if not isinstance(settings, dict):
        return ""
    return str(settings.get("address", "")).strip().lower()


def _is_loopback_node(node: ProxyNode) -> bool:
    return _node_address(node) in _LOOPBACK_ADDRESSES


def member_tag_prefix(balancer_tag: str) -> str:
    """Xray selector is prefix-match; 3x-ui 3.7.0 uses bal-{id}-."""
    return f"bal-{_slugify(balancer_tag)}-"


def _retag_pool_nodes(balancer: BalancerRule, nodes: list[ProxyNode]) -> list[ProxyNode]:
    prefix = member_tag_prefix(balancer.tag)
    used_tags: set[str] = set()
    retagged: list[ProxyNode] = []
    for node in nodes:
        protocol = str(node.protocol or "other").strip().lower() or "other"
        base = f"{prefix}{protocol}"
        tag = _ensure_unique(base, used_tags)
        used_tags.add(tag)
        retagged.append(node.with_tag(tag))
    return retagged


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


def _attach_burst_observatory(config: dict[str, Any], prefix: str) -> None:
    """leastPing/leastLoad: 3x-ui 3.7.0 emits burstObservatory, not observatory."""
    config.pop("observatory", None)
    config["burstObservatory"] = {
        "subjectSelector": [prefix],
        "pingConfig": {
            "destination": _PROBE_URL,
            "interval": "1m",
            "sampling": 2,
            "timeout": "5s",
            "httpMethod": "HEAD",
        },
    }


def _routing_for_balancer(
    template_config: dict[str, Any],
    *,
    selector_prefix: str,
    strategy_type: str,
    fallback_tag: str,
) -> dict[str, Any]:
    base = template_config.get("routing")
    routing: dict[str, Any] = copy.deepcopy(base) if isinstance(base, dict) else {}
    rewritten: list[dict[str, Any]] = []
    has_balancer_rule = False
    for rule in routing.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        rule = copy.deepcopy(rule)
        if rule.get("outboundTag") == "proxy":
            rule.pop("outboundTag", None)
            rule["balancerTag"] = _XRAY_BALANCER_TAG
        if rule.get("balancerTag") == _XRAY_BALANCER_TAG:
            has_balancer_rule = True
        rewritten.append(rule)
    if not has_balancer_rule:
        rewritten.append(
            {
                "type": "field",
                "network": "tcp,udp",
                "balancerTag": _XRAY_BALANCER_TAG,
            }
        )
    balancer_entry: dict[str, Any] = {
        "tag": _XRAY_BALANCER_TAG,
        "selector": [selector_prefix],
        "strategy": {"type": strategy_type},
    }
    if fallback_tag:
        balancer_entry["fallbackTag"] = fallback_tag
    routing["balancers"] = [balancer_entry]
    routing["rules"] = rewritten
    routing.setdefault("domainStrategy", "AsIs")
    return routing


def _build_balancer_config(
    template_config: dict[str, Any],
    nodes: list[ProxyNode],
    balancer: BalancerRule,
    *,
    all_nodes: list[ProxyNode] | None = None,
) -> dict[str, Any] | None:
    usable = [node for node in nodes if not _is_loopback_node(node)]
    retagged = _retag_pool_nodes(balancer, usable)
    if not retagged:
        _log_balancer_resolution(balancer, all_nodes or nodes)
        return None

    config = copy.deepcopy(template_config)
    proxy_outbounds = [copy.deepcopy(node.outbound) for node in retagged]
    config["outbounds"] = proxy_outbounds + _system_outbounds(template_config)
    config["remarks"] = balancer.remarks or balancer.tag
    if _balancer_members_incomplete(balancer, all_nodes or nodes):
        _log_balancer_resolution(balancer, all_nodes or nodes)

    prefix = member_tag_prefix(balancer.tag)
    strategy_type = _STRATEGY_MAP.get(balancer.strategy, "roundRobin")
    # Always set fallbackTag: if balancer dispatch fails (empty match, probe
    # deadlock on iOS TUN), Xray sends traffic to the first real proxy instead
    # of blackholing the tunnel.
    fallback_tag = retagged[0].tag
    config["routing"] = _routing_for_balancer(
        template_config,
        selector_prefix=prefix,
        strategy_type=strategy_type,
        fallback_tag=fallback_tag,
    )
    config.pop("observatory", None)
    if balancer.strategy in _OBSERVATORY_STRATEGIES:
        _attach_burst_observatory(config, prefix)
    else:
        config.pop("burstObservatory", None)
    return config


def _balancer_pool_nodes(
    balancer: BalancerRule,
    nodes: list[ProxyNode],
) -> list[ProxyNode]:
    member_tags = set(_resolve_balancer_members(balancer, nodes))
    if not member_tags:
        return []
    return [
        node
        for node in nodes
        if node.tag in member_tags and not _is_loopback_node(node)
    ]


def _node_hidden_as_standalone(
    node: ProxyNode, rules: TransformRules, nodes: list[ProxyNode]
) -> bool:
    for balancer in rules.balancers:
        if not balancer.hide_members:
            continue
        if node.tag in _resolve_balancer_members(balancer, nodes):
            return True
    return False


def _build_grouped_output(
    configs: list[dict[str, Any]],
    nodes: list[ProxyNode],
    rules: TransformRules,
) -> list[dict[str, Any]]:
    nodes_by_index = {node.source_index: node for node in nodes}
    emitted_balancers: set[str] = set()
    result: list[dict[str, Any]] = []

    for index, config in enumerate(configs):
        node = nodes_by_index.get(index)
        if node is None:
            result.append(copy.deepcopy(config))
            continue

        for balancer in rules.balancers:
            if balancer.tag in emitted_balancers:
                continue
            pool_nodes = _balancer_pool_nodes(balancer, nodes)
            if not pool_nodes or node.tag not in {item.tag for item in pool_nodes}:
                continue
            template = configs[pool_nodes[0].source_index]
            built = _build_balancer_config(
                template, pool_nodes, balancer, all_nodes=nodes
            )
            if built is None:
                continue
            result.append(built)
            emitted_balancers.add(balancer.tag)

        if not _node_hidden_as_standalone(node, rules, nodes):
            result.append(copy.deepcopy(config))

    for balancer in rules.balancers:
        if balancer.tag in emitted_balancers:
            continue
        _log_balancer_resolution(balancer, nodes)

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
    observatory_prefixes: list[str] = []
    needs_observatory = False
    for balancer in rules.balancers:
        pool = _balancer_pool_nodes(balancer, nodes)
        if not pool:
            continue
        retagged = _retag_pool_nodes(balancer, pool)
        if not retagged:
            continue
        prefix = member_tag_prefix(balancer.tag)
        strategy_type = _STRATEGY_MAP.get(balancer.strategy, "roundRobin")
        entry: dict[str, Any] = {
            "tag": balancer.tag,
            "selector": [prefix],
            "strategy": {"type": strategy_type},
            "fallbackTag": retagged[0].tag,
        }
        if balancer.strategy in _OBSERVATORY_STRATEGIES:
            needs_observatory = True
            if prefix not in observatory_prefixes:
                observatory_prefixes.append(prefix)
        balancers_json.append(entry)

    default_balancer = rules.output.default_balancer or (
        balancers_json[0]["tag"] if balancers_json else ""
    )
    routing: dict[str, Any] = {"domainStrategy": "AsIs", "balancers": balancers_json}
    if default_balancer:
        routing["rules"] = [
            {"type": "field", "network": "tcp,udp", "balancerTag": default_balancer}
        ]
    config["routing"] = routing
    config.pop("observatory", None)
    if needs_observatory and observatory_prefixes:
        _attach_burst_observatory(config, observatory_prefixes[0])
        if len(observatory_prefixes) > 1:
            config["burstObservatory"]["subjectSelector"] = observatory_prefixes
    else:
        config.pop("burstObservatory", None)
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
            built_items: list[dict[str, Any]] = []
            first_balancer = self._rules.balancers[0]
            for node in nodes:
                built = _build_balancer_config(
                    configs[node.source_index], [node], first_balancer
                )
                if built is not None:
                    built_items.append(built)
            return built_items or payload

        return _build_single_merged_config(configs[0], nodes, self._rules)