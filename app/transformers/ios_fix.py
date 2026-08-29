"""iOS-FIX: passthrough + HAPP iPhone / Xray balancer parser fixes.

1. First inbound mixed → socks (HAPP iOS / 3x-ui#3718).
2. Keep the 3x-ui balancer type; only rewrite JSON so LibXray starts on iOS:
   - leastPing  → observatory (not burst), fallbackTag, gstatic, concurrency
   - leastLoad  → burstObservatory, connectivity="", fallbackTag, gstatic
   - roundRobin / random → roundRobin, no fallbackTag, no observatory
     (3x-ui#2724: fallbackTag registers Observatory)
   Ordinary single-proxy profiles are not rewritten.
3. Strip sniffing fakedns (no fakedns inbound in 3x-ui JSON).
"""

from __future__ import annotations

import copy
from typing import Any

from app.models.subscription import SubscriptionPayload

_PROBE_URL = "https://www.gstatic.com/generate_204"
_PROBE_INTERVAL = "20s"
_BURST_TIMEOUT = "5s"
_BURST_SAMPLING = 2
_LEAST_PING_TYPES = frozenset({"leastping", "least_ping"})
_LEAST_LOAD_TYPES = frozenset({"leastload", "least_load"})
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


def _strategy_settings(balancer: dict[str, Any]) -> Any:
    strategy = balancer.get("strategy")
    if isinstance(strategy, dict):
        return strategy.get("settings")
    return None


def _apply_fallback(entry: dict[str, Any], config: dict[str, Any], selector: list[Any]) -> None:
    fallback = str(entry.get("fallbackTag") or "").strip()
    if not fallback:
        fallback = _first_member_tag(config, selector)
    if fallback:
        entry["fallbackTag"] = fallback
    else:
        entry.pop("fallbackTag", None)


def _selector_values(selector: list[Any]) -> list[str]:
    return [str(item) for item in selector if item]


def _burst_sampling(config: dict[str, Any], routing: dict[str, Any]) -> int:
    for block in (config.get("burstObservatory"), routing.get("burstObservatory")):
        if not isinstance(block, dict):
            continue
        ping = block.get("pingConfig")
        if not isinstance(ping, dict):
            continue
        try:
            sampling = int(ping.get("sampling") or 0)
        except (TypeError, ValueError):
            continue
        if sampling > 0:
            return sampling
    return _BURST_SAMPLING


def _fix_panel_balancer(config: dict[str, Any]) -> None:
    """Keep the 3x-ui strategy; rewrite only the iOS/Xray parser traps.

    Do not flatten members or rewrite ordinary proxies (stats/dns/policy).
    """
    routing = config.get("routing")
    if not isinstance(routing, dict):
        return
    balancers = routing.get("balancers")
    if not isinstance(balancers, list) or not balancers:
        return

    probe_url = _existing_probe_url(config, routing)
    sampling = _burst_sampling(config, routing)
    rewritten: list[dict[str, Any]] = []
    ping_selectors: list[str] = []
    load_selectors: list[str] = []

    for balancer in balancers:
        if not isinstance(balancer, dict):
            continue
        entry = copy.deepcopy(balancer)
        selector = entry.get("selector")
        if not isinstance(selector, list) or not selector:
            continue
        stype = _balancer_strategy_type(entry)
        prefixes = _selector_values(selector)

        if stype in _LEAST_PING_TYPES:
            entry["strategy"] = {"type": "leastPing"}
            _apply_fallback(entry, config, selector)
            ping_selectors.extend(prefixes)
            rewritten.append(entry)
            continue

        if stype in _LEAST_LOAD_TYPES:
            settings = _strategy_settings(entry)
            if isinstance(settings, dict) and settings:
                entry["strategy"] = {"type": "leastLoad", "settings": copy.deepcopy(settings)}
            else:
                entry["strategy"] = {"type": "leastLoad"}
            _apply_fallback(entry, config, selector)
            load_selectors.extend(prefixes)
            rewritten.append(entry)
            continue

        # roundRobin / random / unknown: fallbackTag registers Observatory.
        entry["strategy"] = {"type": "roundRobin"}
        entry.pop("fallbackTag", None)
        rewritten.append(entry)

    config.pop("burstObservatory", None)
    config.pop("observatory", None)
    routing.pop("burstObservatory", None)
    routing.pop("observatory", None)

    if rewritten:
        routing["balancers"] = rewritten
    else:
        routing.pop("balancers", None)
        return

    # Both types register Observatory; never emit both in one config.
    # leastLoad needs burst HealthPing; leastPing can read burst too.
    load_selectors = _unique(load_selectors)
    ping_selectors = _unique(ping_selectors)
    if load_selectors:
        config["burstObservatory"] = {
            "subjectSelector": _unique(load_selectors + ping_selectors),
            "pingConfig": {
                "destination": probe_url,
                "connectivity": "",
                "interval": _PROBE_INTERVAL,
                "sampling": sampling,
                "timeout": _BURST_TIMEOUT,
                "httpMethod": "HEAD",
            },
        }
    elif ping_selectors:
        config["observatory"] = {
            "subjectSelector": ping_selectors,
            "probeUrl": probe_url,
            "probeInterval": _PROBE_INTERVAL,
            "enableConcurrency": True,
        }
