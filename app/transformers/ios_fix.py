"""iOS-FIX: passthrough + HAPP iPhone fixes.

1. First inbound mixed → socks (3x-ui / HAPP iOS issue).
2. 3x-ui client-side balancer profiles: drop observatory and use roundRobin.
   leastPing + burstObservatory probes through the iOS TUN and blackholes the
   connection; roundRobin + fallbackTag keeps Автовыбор working.
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
    if isinstance(first, dict) and str(first.get("protocol", "")).strip().lower() == "mixed":
        first["protocol"] = "socks"


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
        if fallback and not entry.get("fallbackTag"):
            entry["fallbackTag"] = fallback
        rewritten.append(entry)
    if rewritten:
        routing["balancers"] = rewritten
    else:
        routing.pop("balancers", None)
