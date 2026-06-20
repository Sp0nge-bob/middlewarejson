from app.models.inbound import extract_transport_path
from app.models.nodes import ProxyNode
from app.models.rules_schema import MatchRule


def node_matches(node: ProxyNode, rule: MatchRule) -> bool:
    if rule.fingerprint_equals:
        if node.fingerprint not in rule.fingerprint_equals:
            return False

    if rule.remarks_equals:
        if node.remarks not in rule.remarks_equals:
            return False

    if rule.remarks_contains:
        if not any(part in node.remarks for part in rule.remarks_contains):
            return False

    if rule.flag and rule.flag not in node.remarks:
        return False

    if rule.network_in and node.network not in rule.network_in:
        return False

    if rule.protocol and node.protocol != rule.protocol:
        return False

    if rule.network and node.network != rule.network:
        return False

    if rule.address_equals:
        address = _node_address(node)
        if address not in rule.address_equals:
            return False

    if rule.path_equals:
        path = _node_path(node)
        if path not in rule.path_equals:
            return False

    if rule.security:
        if _node_security(node) != rule.security:
            return False

    if rule.port is not None:
        if _node_port(node) != rule.port:
            return False

    return True


def _node_settings(node: ProxyNode) -> dict:
    settings = node.outbound.get("settings", {})
    return settings if isinstance(settings, dict) else {}


def _node_stream(node: ProxyNode) -> dict:
    stream = node.outbound.get("streamSettings", {})
    return stream if isinstance(stream, dict) else {}


def _node_address(node: ProxyNode) -> str:
    return str(_node_settings(node).get("address", ""))


def _node_path(node: ProxyNode) -> str:
    return extract_transport_path(_node_stream(node))


def _node_security(node: ProxyNode) -> str:
    return str(_node_stream(node).get("security", ""))


def _node_port(node: ProxyNode) -> int:
    port_raw = _node_settings(node).get("port", 0)
    try:
        return int(port_raw)
    except (TypeError, ValueError):
        return 0