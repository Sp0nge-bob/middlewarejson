"""iOS-FIX: passthrough + HAPP iPhone / Xray balancer parser fixes.

1. First inbound mixed → socks (HAPP iOS / 3x-ui#3718).
2. Keep the 3x-ui balancer type; only rewrite JSON so LibXray starts on iOS:
   - leastPing  → observatory (not burst), fallbackTag, gstatic, concurrency
   - leastLoad  → burstObservatory, connectivity="", fallbackTag, gstatic
   - roundRobin / random → same type, no fallbackTag, no observatory
     (3x-ui#2724: fallbackTag registers Observatory)
   Ordinary single-proxy profiles are not rewritten.
3. Strip sniffing fakedns (no fakedns inbound in 3x-ui JSON).
Composed allowlist profiles retain their validated graph, fallback and DNS order.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from app.models.subscription import SubscriptionPayload
from app.features.allowlist_balancer import is_allowlist_profile, validate_allowlist_profile

_PROBE_URL = "https://www.gstatic.com/generate_204"
_PROBE_INTERVAL = "20s"
_BURST_TIMEOUT = "5s"
_BURST_SAMPLING = 2
_LEAST_PING_TYPES = frozenset({"leastping", "least_ping"})
_LEAST_LOAD_TYPES = frozenset({"leastload", "least_load"})
_ROUND_ROBIN_TYPES = frozenset({"roundrobin", "round_robin"})
_SYSTEM_PROTOCOLS = frozenset({"freedom", "blackhole", "dns", "loopback"})
_PROXY_PROTOCOLS = frozenset({"vless", "vmess", "trojan", "shadowsocks", "socks", "http",
    "hysteria", "hysteria2", "wireguard", "tuic", "shadowsocks2022"})
logger = logging.getLogger(__name__)


def _rule_has_filters(rule: dict[str, Any]) -> bool:
    # Unknown nonempty match fields are conservatively specific as well. Keep
    # domainMatcher as metadata: it only changes how an existing domain is read.
    metadata = {"type", "port", "network", "outboundTag", "balancerTag", "ruleTag", "domainMatcher", "webhook"}
    return any(value and key not in metadata for key, value in rule.items())


def _dns_networks(rule: dict[str, Any]) -> set[str]:
    value = rule.get("network")
    if not value:
        return {"tcp", "udp"}
    return set(str(value).lower().replace(" ", "").split(",")) & {"tcp", "udp"}


def _port_can_match_dns(rule: dict[str, Any]) -> bool:
    value = rule.get("port")
    if value is None or value == "":
        return True
    for part in str(value).split(","):
        bounds = part.strip().split("-")
        try:
            if len(bounds) == 1 and int(bounds[0]) == 53:
                return True
            if len(bounds) == 2 and int(bounds[0]) <= 53 <= int(bounds[1]):
                return True
        except ValueError:
            continue
    return False


def apply_ios_fix(payload: SubscriptionPayload) -> SubscriptionPayload:
    return _process_ios_fix(payload, inject_routing=False)


def apply_ios_fix_dns(payload: SubscriptionPayload) -> SubscriptionPayload:
    return _process_ios_fix(payload, inject_routing=True)


def _process_ios_fix(payload: SubscriptionPayload, *, inject_routing: bool) -> SubscriptionPayload:
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
        if inject_routing:
            _inject_routing_rules(fixed)
        result.append(fixed)
    if isinstance(payload, list):
        return result
    return result[0] if result else payload


def _inject_routing_rules(config: dict[str, Any]) -> None:
    if is_allowlist_profile(config):
        validate_allowlist_profile(config)
        return  # The graph already includes DNS after its service routes.
    original_routing = config.get("routing")
    routing = original_routing if isinstance(original_routing, dict) else {}
    original_rules = routing.get("rules")
    rules = original_rules if isinstance(original_rules, list) else []
    outbounds = config.get("outbounds")
    outbounds = outbounds if isinstance(outbounds, list) else []
    tagged = {str(ob["tag"]): ob for ob in outbounds if isinstance(ob, dict) and ob.get("tag")}
    proxy_tags = [tag for tag, ob in tagged.items()
                  if str(ob.get("protocol", "")).strip().lower() in _PROXY_PROTOCOLS]
    balancers = routing.get("balancers")
    balancers = balancers if isinstance(balancers, list) else []
    valid_balancers = []
    for balancer in balancers:
        if not isinstance(balancer, dict) or not balancer.get("tag"):
            continue
        selectors = balancer.get("selector")
        if not isinstance(selectors, list) or not selectors or any(not isinstance(p, str) or not p for p in selectors):
            continue
        members = [tag for tag in tagged if any(tag.startswith(prefix) for prefix in selectors)]
        fallback = balancer.get("fallbackTag")
        if members and all(tag in proxy_tags for tag in members) and (not fallback or fallback in proxy_tags):
            valid_balancers.append(str(balancer["tag"]))

    def has_valid_target(rule: dict[str, Any]) -> bool:
        outbound = rule.get("outboundTag")
        balancer = rule.get("balancerTag")
        return bool((isinstance(outbound, str) and outbound in tagged and not balancer)
                    or (isinstance(balancer, str) and balancer in valid_balancers and not outbound))

    insertion = len(rules)
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or _rule_has_filters(rule) or not _dns_networks(rule) or not _port_can_match_dns(rule):
            continue
        if rule.get("port") in (53, "53") and _dns_networks(rule) == {"tcp", "udp"} and has_valid_target(rule):
            return  # Preserve an explicit reachable all-DNS policy, including direct/block.
        if rule.get("port") in (53, "53") and _dns_networks(rule) != {"tcp", "udp"}:
            continue  # Keep TCP-only/UDP-only DNS exceptions before the new catch-all.
        insertion = index
        break  # Insert before the first broad fallback that could otherwise win.

    target: dict[str, Any] | None = None
    if valid_balancers:
        target = {"balancerTag": valid_balancers[0]}
    else:
        preferred = [rule.get("outboundTag") for rule in rules if isinstance(rule, dict)
                     and isinstance(rule.get("outboundTag"), str) and rule.get("outboundTag") in proxy_tags]
        if preferred or proxy_tags:
            target = {"outboundTag": (preferred or proxy_tags)[0]}
    if target is None:
        logger.warning("DNS catch-all not added: no validated proxy target")
        return  # Do not invent absent tags or turn a system outbound into a proxy.
    rules.insert(insertion, {"type": "field", "port": 53, "network": "tcp,udp", **target})
    if not isinstance(original_routing, dict):
        config["routing"] = {"domainStrategy": "AsIs", "rules": rules}
    elif not isinstance(original_rules, list):
        routing["rules"] = rules


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
        routing = config.get("routing")
        if isinstance(routing, dict) and isinstance(routing.get("rules"), list):
            for rule in routing["rules"]:
                if not isinstance(rule, dict):
                    continue
                tags = rule.get("inboundTag")
                if isinstance(tags, list):
                    rule["inboundTag"] = ["socks" if tag == "mixed" else tag for tag in tags]
                elif tags == "mixed":
                    rule["inboundTag"] = "socks"
    if str(first.get("protocol", "")).strip().lower() == "socks":
        first["listen"] = "127.0.0.1"


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
    if isinstance(nested, dict):
        for key, value in nested.items():
            if key not in block or block[key] is None:
                block[key] = copy.deepcopy(value)

    # v26.9.9 parses these fields as comma-separated strings, not arrays.
    for key in ("pinnedPeerCertSha256", "verifyPeerCertByName"):
        value = block.get(key)
        if isinstance(value, list):
            if any(not isinstance(item, str) for item in value):
                raise ValueError(f"invalid TLS {key}")
            block[key] = ",".join(value)

    # Очищаем фиктивные значения verifyPeerCertByName ("0", "false", "none", ""),
    # из-за которых Xray требует совпадения SAN сертификата с "0" и ломает TLS в Happ.
    vcn = str(block.get("verifyPeerCertByName", "")).strip().lower()
    if vcn in ("0", "false", "null", "none", ""):
        block.pop("verifyPeerCertByName", None)


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
    if is_allowlist_profile(config):
        validate_allowlist_profile(config)
        return  # Keep the monitored roundRobin fallback and shared observer.
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

        # random / roundRobin: fallbackTag registers Observatory (3x-ui#2724).
        if stype in _ROUND_ROBIN_TYPES:
            entry["strategy"] = {"type": "roundRobin"}
        else:
            entry["strategy"] = {"type": "random"}
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
