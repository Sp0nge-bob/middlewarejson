"""iOS-FIX: passthrough + HAPP iPhone / Xray balancer parser fixes.

1. First inbound mixed → socks (HAPP iOS / 3x-ui#3718).
2. Keep 3x-ui Автовыбор as a real balancer (all members + selector).
   Parser trap: RoundRobinStrategy/RandomStrategy.InjectContext calls
   core.RequireFeatures(Observatory) whenever fallbackTag is non-empty
   (Xray-core app/router/balancing.go, discussion #5913, 3x-ui#2724,
   3x-ui 5cf8a08). Without an observatory block the core never starts:
   «not all dependencies are resolved». leastPing/leastLoad need live
   probes, which on iOS go through the TUN and blackhole traffic. So:
   roundRobin, drop fallbackTag, drop observatory/burstObservatory.
   Ordinary single-proxy profiles are not rewritten.
3. Strip sniffing fakedns (no fakedns inbound in 3x-ui JSON).
"""

from __future__ import annotations

import copy
from typing import Any

from app.models.subscription import SubscriptionPayload


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


def _fix_panel_balancer(config: dict[str, Any]) -> None:
    """Keep the pool; fix the Xray JSON parser trap around fallbackTag.

    Do not flatten members or rewrite ordinary proxies (stats/dns/policy).
    """
    routing = config.get("routing")
    if not isinstance(routing, dict):
        return
    balancers = routing.get("balancers")
    if not isinstance(balancers, list) or not balancers:
        return

    # Observatory is a top-level Xray key; some templates nest it in routing.
    config.pop("observatory", None)
    config.pop("burstObservatory", None)
    routing.pop("observatory", None)
    routing.pop("burstObservatory", None)

    rewritten: list[dict[str, Any]] = []
    for balancer in balancers:
        if not isinstance(balancer, dict):
            continue
        entry = copy.deepcopy(balancer)
        selector = entry.get("selector")
        if not isinstance(selector, list) or not selector:
            continue
        # leastPing/leastLoad cannot start without observatory; roundRobin
        # can, but only if fallbackTag is absent (RequireFeatures trap).
        entry["strategy"] = {"type": "roundRobin"}
        entry.pop("fallbackTag", None)
        rewritten.append(entry)
    if rewritten:
        routing["balancers"] = rewritten
    else:
        routing.pop("balancers", None)
