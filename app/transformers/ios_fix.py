"""iOS-FIX: passthrough + HAPP iPhone / Xray balancer parser fixes.

1. First inbound mixed → socks (HAPP iOS / 3x-ui#3718).
2. Keep 3x-ui Автовыбор as a real balancer (all members + selector).
   leastPing as designed needs top-level `observatory` (not burstObservatory):
   Xray author: leastPing ↔ observatory, leastLoad ↔ burstObservatory.
   3x-ui JSON sub emits burstObservatory + google generate_204; burst does
   not probe at start (#3058) and connectivity probes can loop in TUN.
   So: keep leastPing + fallbackTag, swap burst → observatory, probe via
   gstatic, enableConcurrency. roundRobin/random still drop fallbackTag
   without observatory (3x-ui#2724, Xray-core#5913).
   Ordinary single-proxy profiles are not rewritten.
3. Strip sniffing fakedns (no fakedns inbound in 3x-ui JSON).
"""

from __future__ import annotations

import copy
from typing import Any

from app.models.subscription import SubscriptionPayload

_PROBE_URL = "https://www.gstatic.com/generate_204"
_PROBE_INTERVAL = "20s"
_LEAST_PING_TYPES = frozenset({"leastping", "least_ping", "leastload", "least_load"})
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


def _balancer_strategy_type(balancer: dict[str, Any]) -> str:
    strategy = balancer.get("strategy")
    if isinstance(strategy, dict):
        return str(strategy.get("type") or "").strip().lower()
    if isinstance(strategy, str):
        return strategy.strip().lower()
    return ""


def _sanitize_probe_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return _PROBE_URL
    lowered = raw.lower()
    if "google.com" in lowered:
        return _PROBE_URL
    return raw


def _existing_probe_url(config: dict[str, Any], routing: dict[str, Any]) -> str:
    blocks = [
        config.get("burstObservatory"),
        routing.get("burstObservatory"),
        config.get("observatory"),
        routing.get("observatory"),
    ]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        ping = block.get("pingConfig")
        if isinstance(ping, dict) and ping.get("destination"):
            return _sanitize_probe_url(str(ping.get("destination")))
        if block.get("probeUrl"):
            return _sanitize_probe_url(str(block.get("probeUrl")))
    return _PROBE_URL


def _first_member_tag(config: dict[str, Any], selector: list[Any]) -> str:
    prefixes = [str(item) for item in selector if item]
    outbounds = config.get("outbounds")
    if not prefixes or not isinstance(outbounds, list):
        return ""
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        protocol = str(outbound.get("protocol") or "").strip().lower()
        if protocol in _SYSTEM_PROTOCOLS:
            continue
        tag = str(outbound.get("tag") or "")
        if tag and any(tag.startswith(prefix) for prefix in prefixes):
            return tag
    return ""


def _unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _fix_panel_balancer(config: dict[str, Any]) -> None:
    """Keep the pool; make 3x-ui leastPing work on iPhone LibXray.

    Do not flatten members or rewrite ordinary proxies (stats/dns/policy).
    """
    routing = config.get("routing")
    if not isinstance(routing, dict):
        return
    balancers = routing.get("balancers")
    if not isinstance(balancers, list) or not balancers:
        return

    probe_url = _existing_probe_url(config, routing)
    rewritten: list[dict[str, Any]] = []
    observatory_selectors: list[str] = []

    for balancer in balancers:
        if not isinstance(balancer, dict):
            continue
        entry = copy.deepcopy(balancer)
        selector = entry.get("selector")
        if not isinstance(selector, list) or not selector:
            continue
        stype = _balancer_strategy_type(entry)
        if stype in _LEAST_PING_TYPES:
            entry["strategy"] = {"type": "leastPing"}
            fallback = str(entry.get("fallbackTag") or "").strip()
            if not fallback:
                fallback = _first_member_tag(config, selector)
            if fallback:
                entry["fallbackTag"] = fallback
            else:
                entry.pop("fallbackTag", None)
            observatory_selectors.extend(str(item) for item in selector if item)
            rewritten.append(entry)
            continue
        # random / roundRobin: fallbackTag registers Observatory (3x-ui#2724).
        entry["strategy"] = {"type": "roundRobin"}
        entry.pop("fallbackTag", None)
        rewritten.append(entry)

    config.pop("burstObservatory", None)
    routing.pop("burstObservatory", None)
    routing.pop("observatory", None)

    if rewritten:
        routing["balancers"] = rewritten
    else:
        routing.pop("balancers", None)
        config.pop("observatory", None)
        return

    selectors = _unique(observatory_selectors)
    if selectors:
        config["observatory"] = {
            "subjectSelector": selectors,
            "probeUrl": probe_url,
            "probeInterval": _PROBE_INTERVAL,
            "enableConcurrency": True,
        }
    else:
        config.pop("observatory", None)
