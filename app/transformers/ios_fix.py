"""iOS-FIX: passthrough + HAPP iPhone fixes.

1. First inbound mixed → socks (HAPP iOS / 3x-ui#3718).
2. 3x-ui Автовыбор: drop observatory, force roundRobin (leastPing probes
   blackhole the iOS TUN).
3. Strip sniffing fakedns (no fakedns inbound in 3x-ui JSON).
4. Flatten leftover tlsSettings.settings from the panel.
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
        _fix_panel_balancer(fixed)
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


def _first_proxy_tag(config: dict[str, Any]) -> str:
    outbounds = config.get("outbounds")
    if not isinstance(outbounds, list):
        return ""
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        protocol = str(outbound.get("protocol", ""))
        tag = str(outbound.get("tag", ""))
        if tag == "proxy" or protocol not in _SYSTEM_PROTOCOLS:
            return tag
    return ""


def _fix_panel_balancer(config: dict[str, Any]) -> None:
    routing = config.get("routing")
    if not isinstance(routing, dict):
        return
    balancers = routing.get("balancers")
    if not isinstance(balancers, list) or not balancers:
        return

    config.pop("observatory", None)
    config.pop("burstObservatory", None)

    fallback = _first_proxy_tag(config)
    rewritten: list[dict[str, Any]] = []
    for balancer in balancers:
        if not isinstance(balancer, dict):
            continue
        entry = copy.deepcopy(balancer)
        entry["strategy"] = {"type": "roundRobin"}
        selector = entry.get("selector")
        if not isinstance(selector, list) or not selector:
            continue
        if fallback:
            entry["fallbackTag"] = fallback
        rewritten.append(entry)
    if rewritten:
        routing["balancers"] = rewritten
    else:
        routing.pop("balancers", None)
