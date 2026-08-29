"""iOS-FIX: passthrough + HAPP iPhone fixes.

1. First inbound mixed → socks (HAPP iOS / 3x-ui#3718).
2. Flatten 3x-ui Автовыбор to a normal proxy profile. HAPP 4.11 LibXray
   dies with "not all dependencies are resolved" on routing.balancers
   unless observatory is loaded; observatory probes blackhole the TUN.
3. Strip sniffing fakedns, stats, dns.tag leftovers from 3x-ui default.json.
"""

from __future__ import annotations

import copy
from typing import Any

from app.models.subscription import SubscriptionPayload

_SYSTEM_PROTOCOLS = frozenset({"freedom", "blackhole", "dns"})


def apply_ios_fix(payload: SubscriptionPayload) -> SubscriptionPayload:
    configs = payload if isinstance(payload, list) else [payload]
    result: list[Any] = []
    for config in configs:
        if not isinstance(config, dict):
            result.append(config)
            continue
        fixed = copy.deepcopy(config)
        _fix_first_inbound(fixed)
        _strip_fakedns(fixed)
        _flatten_tls_settings(fixed)
        _strip_stats_and_dns_tag(fixed)
        _flatten_panel_balancer(fixed)
        result.append(fixed)
    if isinstance(payload, list):
        return result
    return result[0] if result else payload


def _fix_first_inbound(config: dict[str, Any]) -> None:
    inbounds = config.get("inbounds")
    if not isinstance(inbounds, list) or not inbounds:
        return
    first = inbounds[0]
    if not isinstance(first, dict):
        return
    if str(first.get("protocol", "")).strip().lower() == "mixed":
        first["protocol"] = "socks"
    if str(first.get("protocol", "")).strip().lower() == "socks" and first.get("tag") == "mixed":
        first["tag"] = "socks"


def _strip_fakedns(config: dict[str, Any]) -> None:
    inbounds = config.get("inbounds")
    if not isinstance(inbounds, list):
        return
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        sniffing = inbound.get("sniffing")
        if not isinstance(sniffing, dict):
            continue
        dest = sniffing.get("destOverride")
        if isinstance(dest, list):
            sniffing["destOverride"] = [item for item in dest if item != "fakedns"]


def _flatten_tls_block(block: dict[str, Any]) -> None:
    nested = block.pop("settings", None)
    if not isinstance(nested, dict):
        return
    if not block.get("fingerprint") and nested.get("fingerprint"):
        block["fingerprint"] = nested["fingerprint"]


def _flatten_tls_settings(config: dict[str, Any]) -> None:
    outbounds = config.get("outbounds")
    if not isinstance(outbounds, list):
        return
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        stream = outbound.get("streamSettings")
        if not isinstance(stream, dict):
            continue
        tls = stream.get("tlsSettings")
        if isinstance(tls, dict):
            _flatten_tls_block(tls)
        ws = stream.get("wsSettings")
        if isinstance(ws, dict) and ws.get("heartbeatPeriod") == 0:
            ws.pop("heartbeatPeriod", None)


def _is_proxy_outbound(outbound: dict[str, Any]) -> bool:
    protocol = str(outbound.get("protocol", ""))
    tag = str(outbound.get("tag", ""))
    if tag in ("direct", "block"):
        return False
    if tag == "proxy":
        return True
    return protocol not in _SYSTEM_PROTOCOLS and protocol != ""


def _strip_stats_and_dns_tag(config: dict[str, Any]) -> None:
    """HAPP 4.11 LibXray: stats + dns.tag leave features unresolved."""
    config.pop("stats", None)
    policy = config.get("policy")
    if isinstance(policy, dict):
        system = policy.get("system")
        if isinstance(system, dict):
            system.pop("statsOutboundUplink", None)
            system.pop("statsOutboundDownlink", None)
            if not system:
                policy.pop("system", None)
        if not policy:
            config.pop("policy", None)
    dns = config.get("dns")
    if isinstance(dns, dict):
        dns.pop("tag", None)


def _flatten_panel_balancer(config: dict[str, Any]) -> None:
    routing = config.get("routing")
    if not isinstance(routing, dict):
        return
    balancers = routing.get("balancers")
    if not isinstance(balancers, list) or not balancers:
        return

    config.pop("observatory", None)
    config.pop("burstObservatory", None)
    routing.pop("balancers", None)

    outbounds = config.get("outbounds")
    proxies: list[dict[str, Any]] = []
    system: list[dict[str, Any]] = []
    if isinstance(outbounds, list):
        for outbound in outbounds:
            if not isinstance(outbound, dict):
                continue
            if _is_proxy_outbound(outbound):
                proxies.append(outbound)
            else:
                system.append(outbound)

    if proxies:
        first = copy.deepcopy(proxies[0])
        first["tag"] = "proxy"
        config["outbounds"] = [first] + system

    rules: list[dict[str, Any]] = []
    for rule in routing.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        rule = copy.deepcopy(rule)
        if "balancerTag" in rule:
            rule.pop("balancerTag", None)
            rule["outboundTag"] = "proxy"
        rules.append(rule)
    if not any(rule.get("outboundTag") == "proxy" for rule in rules):
        rules.append(
            {"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}
        )
    routing["rules"] = rules
