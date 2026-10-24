"""Compose marked 3x-ui pools. Reachability is measured by the client, not here."""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.models.subscription import SubscriptionPayload
from app.text_encoding import repair_mojibake

logger = logging.getLogger(__name__)

POOL_A = "cf-pool-a"
GUARD_A = "cf-a-check"
POOL_B = "cf-pool-b"
TO_GUARD = "cf-to-a-check"
TO_B = "cf-to-pool-b"
ENTER_GUARD = "cf-enter-a-check"
ENTER_B = "cf-enter-pool-b"
UNAVAILABLE = "cf-unavailable"
DESCRIPTION = "cf-description"
PROFILE_NAME = "Автовыбор — A → Б"
DEFAULT_PROBE_URL = "https://www.gstatic.com/generate_204"
DEFAULT_PROBE_INTERVAL = "20s"

_BALANCER_TAGS = {POOL_A, GUARD_A, POOL_B}
_SYSTEM_PROTOCOLS = {"freedom", "blackhole", "dns"}
_PROXY_PROTOCOLS = {
    "vless", "vmess", "trojan", "shadowsocks", "socks", "http",
    "hysteria", "wireguard", "masque",
}
_MARKER = re.compile(r"\[([aаbв])\]", re.IGNORECASE)
_PROFILE_FIELDS = {"remarks", "outbounds", "routing", "observatory", "burstObservatory", "meta"}


class InvalidPool(ValueError):
    """A pair cannot be composed without changing its other semantics."""


def _description_outbound() -> dict[str, Any]:
    """Static Happ subtitle; every dial is blocked, never a working pool member.

    Keep this complete shape strict: no source credentials, external address,
    inherited transport options or arbitrary outbound chains belong here.
    """
    return {
        "tag": DESCRIPTION,
        "protocol": "vless",
        "settings": {"vnext": [{
            "address": "127.0.0.1", "port": 9,
            "users": [{"id": "00000000-0000-4000-8000-000000000001", "encryption": "none"}],
        }]},
        "streamSettings": {
            "network": "ws", "security": "tls",
            "tlsSettings": {"serverName": "localhost"},
            "wsSettings": {"path": "/"},
            "sockopt": {"domainStrategy": "AsIs", "dialerProxy": UNAVAILABLE},
        },
        "mux": {"enabled": False},
    }


@dataclass
class _Pool:
    config: dict[str, Any]
    balancer: dict[str, Any]
    members: list[dict[str, Any]]
    system: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    routing_options: dict[str, Any]


def _roles(remarks: Any) -> set[str]:
    if not isinstance(remarks, str):
        return set()
    return {"A" if m.lower() in {"a", "а"} else "B" for m in _MARKER.findall(remarks)}


def normalize_profile_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("название должно быть строкой")
    value = repair_mojibake(value).strip()
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("название не должно быть пустым или содержать управляющие символы")
    if _roles(value):
        raise ValueError("метки [A]/[B] предназначены для исходных пулов, а не итогового имени")
    return value


def normalize_profile_flag(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("флаг задаётся двухбуквенным кодом страны")
    value = value.strip()
    if value.lower() in {"", "off", "none"}:
        return ""
    if not re.fullmatch(r"[A-Za-z]{2}", value):
        raise ValueError("укажите код страны RU/NL/DE или off для удаления флага")
    return value.upper()


def normalize_profile_description(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("описание должно быть строкой")
    value = repair_mojibake(value).strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("описание не должно содержать управляющие символы")
    return "auto" if not value or value.lower() == "auto" else value


def _source_meta(config: dict[str, Any]) -> dict[str, Any]:
    meta = config.get("meta", {})
    if not isinstance(meta, dict):
        raise InvalidPool("source meta must be an object")
    return meta


def _automatic_description(pool: _Pool) -> str:
    existing = _source_meta(pool.config).get("serverDescription")
    if isinstance(existing, str) and existing.strip():
        return existing
    outbound = pool.members[0]
    stream = outbound.get("streamSettings", {})
    if not isinstance(stream, dict):
        stream = {}
    protocol = outbound["protocol"].upper()
    network = str(stream.get("network") or "tcp").upper()
    security = str(stream.get("security") or "none").upper()
    return f"{protocol} / {network} / {security} | JSON"


def format_profile_name(name: str, flag_code: str = "") -> str:
    name = normalize_profile_name(name)
    code = normalize_profile_flag(flag_code)
    flag = "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)
    return f"{flag} {name}" if flag else name


def _tagged(items: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise InvalidPool("missing tagged list")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise InvalidPool("tagged item is not an object")
        tag = item.get("tag")
        if not isinstance(tag, str) or not tag.strip() or tag in result:
            raise InvalidPool("empty or duplicate tag")
        result[tag] = item
    return result


def _selectors(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise InvalidPool("missing selector")
    if any(not isinstance(s, str) or not s.strip() for s in value):
        raise InvalidPool("invalid selector")
    return list(dict.fromkeys(value))


def _selected(outbounds: list[dict[str, Any]], selectors: list[str]) -> list[dict[str, Any]]:
    return [ob for ob in outbounds if any(ob["tag"].startswith(s) for s in selectors)]


def _has_chain(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("dialerProxy") or value.get("proxySettings")) or any(
            _has_chain(v) for v in value.values()
        )
    return isinstance(value, list) and any(_has_chain(v) for v in value)


def _identity(outbound: dict[str, Any]) -> str:
    # Ignore tags and mux policy when detecting the same connection twice.
    return json.dumps(
        {k: outbound.get(k) for k in ("protocol", "settings", "streamSettings")},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )


def _read_pool(config: dict[str, Any]) -> _Pool:
    routing = config.get("routing")
    if not isinstance(routing, dict) or routing.get("script"):
        raise InvalidPool("missing routing or unsupported routing script")
    balancers = routing.get("balancers")
    if not isinstance(balancers, list) or len(balancers) != 1:
        raise InvalidPool("a marked profile must contain exactly one source balancer")
    balancer = next(iter(_tagged(balancers).values()))
    strategy = balancer.get("strategy", {})
    stype = strategy.get("type", "") if isinstance(strategy, dict) else strategy
    if not isinstance(stype, str) or stype.lower().replace("_", "") not in {
        "leastping", "leastload", "roundrobin", "random",
    }:
        raise InvalidPool("unsupported source strategy")
    selectors = _selectors(balancer.get("selector"))
    outbounds = list(_tagged(config.get("outbounds")).values())
    if any(not isinstance(ob.get("protocol"), str) for ob in outbounds):
        raise InvalidPool("outbound protocol must be a string")
    if balancer["tag"].startswith("cf-") or any(ob["tag"].startswith("cf-") for ob in outbounds):
        raise InvalidPool("reserved tag namespace")
    inbounds = config.get("inbounds", [])
    if not isinstance(inbounds, list) or any(
        not isinstance(ib, dict) or str(ib.get("tag", "")).startswith("cf-") for ib in inbounds
    ):
        raise InvalidPool("invalid or reserved inbound")
    members = _selected(outbounds, selectors)
    if not members or any(ob.get("protocol") not in _PROXY_PROTOCOLS for ob in members):
        raise InvalidPool("selector must select real proxy members only")
    member_tags = {ob["tag"] for ob in members}
    system = [ob for ob in outbounds if ob["tag"] not in member_tags]
    if any(ob.get("protocol") not in _SYSTEM_PROTOCOLS for ob in system):
        raise InvalidPool("unsupported extra proxy or loopback outbound")
    if any(_has_chain(ob) for ob in outbounds):
        raise InvalidPool("outbound chains require a separate compatibility policy")
    if any(not isinstance(ob.get("settings"), dict) for ob in members):
        raise InvalidPool("proxy member has no settings object")
    identities = [_identity(ob) for ob in members]
    if len(set(identities)) != len(identities):
        raise InvalidPool("duplicate proxy connection within a pool")
    fallback = balancer.get("fallbackTag")
    if "fallbackTag" in balancer and not isinstance(fallback, str):
        raise InvalidPool("source fallback must be a tag string")
    if fallback and fallback not in {ob["tag"] for ob in outbounds}:
        raise InvalidPool("dangling source fallback")
    rules = routing.get("rules", [])
    if not isinstance(rules, list) or any(not isinstance(r, dict) for r in rules):
        raise InvalidPool("invalid routing rules")
    normalized = []
    for rule in rules:
        rule = copy.deepcopy(rule)
        if sum(k in rule for k in ("balancerTag", "outboundTag")) != 1:
            raise InvalidPool("routing rule must have exactly one target")
        if not isinstance(rule.get("balancerTag", rule.get("outboundTag")), str):
            raise InvalidPool("routing target must be a tag string")
        if "balancerTag" in rule:
            if rule["balancerTag"] != balancer["tag"]:
                raise InvalidPool("dangling rule balancer")
            rule["balancerTag"] = POOL_A
        elif rule["outboundTag"] not in {ob["tag"] for ob in system}:
            raise InvalidPool("rule bypasses pool selection or references a missing outbound")
        normalized.append(rule)
    options = {k: v for k, v in routing.items() if k not in {
        "rules", "balancers", "observatory", "burstObservatory",
    }}
    return _Pool(config, balancer, members, system, normalized, options)


def is_allowlist_profile(config: dict[str, Any]) -> bool:
    """Recognize our graph without relying on its editable display name."""
    routing = config.get("routing")
    if not isinstance(routing, dict):
        return False
    balancers = routing.get("balancers")
    return isinstance(balancers, list) and {
        b.get("tag") for b in balancers if isinstance(b, dict) and isinstance(b.get("tag"), str)
    } == _BALANCER_TAGS


def _service_rules() -> list[dict[str, Any]]:
    return [
        {"type": "field", "inboundTag": [ENTER_GUARD], "balancerTag": GUARD_A},
        {"type": "field", "inboundTag": [ENTER_B], "balancerTag": POOL_B},
        {"type": "field", "port": 53, "network": "tcp,udp", "balancerTag": POOL_A},
    ]


def _validate_probe(probe_url: str, probe_interval: str) -> None:
    if not isinstance(probe_url, str) or not isinstance(probe_interval, str):
        raise InvalidPool("invalid probe settings types")
    url = urlsplit(probe_url)
    if any(c.isspace() for c in probe_url) or url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
        raise InvalidPool("probe URL must be HTTPS without credentials or fragment")
    try:
        url.port
    except ValueError as exc:
        raise InvalidPool("invalid probe port") from exc
    if not re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)s", probe_interval) or float(probe_interval[:-1]) <= 0:
        raise InvalidPool("probe interval must be positive seconds")


def validate_allowlist_profile(config: dict[str, Any]) -> None:
    """Validate links and monitor coverage before skipping legacy rewrites."""
    if not is_allowlist_profile(config):
        raise InvalidPool("not a composed profile")
    outbounds = _tagged(config.get("outbounds"))
    if any(not isinstance(ob.get("protocol"), str) for ob in outbounds.values()):
        raise InvalidPool("invalid composed outbound protocol")
    balancers = _tagged(config["routing"]["balancers"])
    expected = {
        POOL_A: ("leastPing", TO_GUARD),
        GUARD_A: ("roundRobin", TO_B),
        POOL_B: ("leastPing", UNAVAILABLE),
    }
    for tag, (strategy, fallback) in expected.items():
        b = balancers[tag]
        if b.get("strategy") != {"type": strategy} or b.get("fallbackTag") != fallback:
            raise InvalidPool("invalid priority strategy or fallback")
        matches = _selected(list(outbounds.values()), _selectors(b.get("selector")))
        if not matches or any(ob.get("protocol") not in _PROXY_PROTOCOLS for ob in matches):
            raise InvalidPool("invalid priority pool members")
    selectors_a = _selectors(balancers[POOL_A]["selector"])
    selectors_b = _selectors(balancers[POOL_B]["selector"])
    if balancers[GUARD_A]["selector"] != balancers[POOL_A]["selector"]:
        raise InvalidPool("guard differs from pool A")
    tags_a = {ob["tag"] for ob in _selected(list(outbounds.values()), selectors_a)}
    tags_b = {ob["tag"] for ob in _selected(list(outbounds.values()), selectors_b)}
    if tags_a & tags_b:
        raise InvalidPool("priority selectors overlap")
    if DESCRIPTION in tags_a | tags_b:
        raise InvalidPool("description outbound selected as a real pool member")
    members_a = _selected(list(outbounds.values()), selectors_a)
    members_b = _selected(list(outbounds.values()), selectors_b)
    if {_identity(ob) for ob in members_a} & {_identity(ob) for ob in members_b}:
        raise InvalidPool("duplicate connection across composed pools")
    for tag, outbound in outbounds.items():
        if tag != DESCRIPTION and _has_chain(outbound):
            raise InvalidPool("unsupported chain outside description outbound")
        if tag not in tags_a | tags_b | {TO_GUARD, TO_B, UNAVAILABLE, DESCRIPTION} and outbound.get("protocol") not in _SYSTEM_PROTOCOLS:
            raise InvalidPool("extra proxy outside composed pools")
    for tag, inbound in ((TO_GUARD, ENTER_GUARD), (TO_B, ENTER_B)):
        if outbounds.get(tag) != {"tag": tag, "protocol": "loopback", "settings": {"inboundTag": inbound}}:
            raise InvalidPool("invalid loopback link")
    if outbounds.get(UNAVAILABLE) != {"tag": UNAVAILABLE, "protocol": "blackhole", "settings": {}}:
        raise InvalidPool("missing terminal blackhole")
    default_tag = config["outbounds"][0]["tag"]
    if DESCRIPTION in outbounds:
        if default_tag != DESCRIPTION or outbounds[DESCRIPTION] != _description_outbound():
            raise InvalidPool("invalid blocked description outbound")
    elif default_tag != UNAVAILABLE:
        raise InvalidPool("unsafe default outbound")
    routing = config["routing"]
    if routing.get("script"):
        raise InvalidPool("routing script overrides priority graph")
    rules = routing.get("rules")
    if not isinstance(rules, list) or rules[:3] != _service_rules():
        raise InvalidPool("invalid service/DNS rule ordering")
    for rule in rules:
        if not isinstance(rule, dict) or sum(k in rule for k in ("outboundTag", "balancerTag")) != 1:
            raise InvalidPool("invalid composed routing rule")
        if not isinstance(rule.get("balancerTag", rule.get("outboundTag")), str):
            raise InvalidPool("invalid composed routing target")
        if "balancerTag" in rule and rule["balancerTag"] not in balancers:
            raise InvalidPool("missing composed rule balancer")
        if "outboundTag" in rule and rule["outboundTag"] not in outbounds:
            raise InvalidPool("missing composed rule outbound")
        if rule.get("outboundTag") == DESCRIPTION:
            raise InvalidPool("routing rule targets description outbound")
    if "observatory" in routing or "burstObservatory" in routing or "burstObservatory" in config:
        raise InvalidPool("multiple or nested observers in composed graph")
    observer = config.get("observatory")
    if not isinstance(observer, dict) or observer.get("enableConcurrency") is not True:
        raise InvalidPool("missing concurrent observer")
    _validate_probe(observer.get("probeUrl", ""), observer.get("probeInterval", ""))
    monitored = {ob["tag"] for ob in _selected(list(outbounds.values()), _selectors(observer.get("subjectSelector")))}
    if monitored != tags_a | tags_b:
        raise InvalidPool("observer must cover exactly A and B")


def _build(a: _Pool, b: _Pool, probe_url: str, interval: str, profile_name: str, description: str) -> dict[str, Any]:
    common_a = {k: v for k, v in a.config.items() if k not in _PROFILE_FIELDS}
    common_b = {k: v for k, v in b.config.items() if k not in _PROFILE_FIELDS}
    if common_a != common_b or a.routing_options != b.routing_options or a.rules != b.rules:
        raise InvalidPool("source DNS/inbound/policy/routing templates differ")
    meta_a, meta_b = _source_meta(a.config), _source_meta(b.config)
    if ({k: v for k, v in meta_a.items() if k != "serverDescription"}
            != {k: v for k, v in meta_b.items() if k != "serverDescription"}):
        raise InvalidPool("source metadata differs beyond serverDescription")
    if {_identity(ob) for ob in a.members} & {_identity(ob) for ob in b.members}:
        raise InvalidPool("the same proxy connection appears in both pools")
    system: dict[str, dict[str, Any]] = {}
    for ob in a.system + b.system:
        if ob["tag"] in system and system[ob["tag"]] != ob:
            raise InvalidPool("conflicting system outbounds")
        system[ob["tag"]] = ob
    merged = a.members + b.members + list(system.values())
    _tagged(merged)
    selectors_a = _selectors(a.balancer["selector"])
    selectors_b = _selectors(b.balancer["selector"])
    for pool, selectors in ((a, selectors_a), (b, selectors_b)):
        if {ob["tag"] for ob in _selected(merged, selectors)} != {ob["tag"] for ob in pool.members}:
            raise InvalidPool("selector changes membership after composition")
    result = copy.deepcopy(a.config)
    result["remarks"] = profile_name
    result["meta"] = {
        **copy.deepcopy(meta_a),
        "serverDescription": _automatic_description(a) if description == "auto" else description,
    }
    result["outbounds"] = [
        _description_outbound(),
        {"tag": UNAVAILABLE, "protocol": "blackhole", "settings": {}},
        *copy.deepcopy(merged),
        {"tag": TO_GUARD, "protocol": "loopback", "settings": {"inboundTag": ENTER_GUARD}},
        {"tag": TO_B, "protocol": "loopback", "settings": {"inboundTag": ENTER_B}},
    ]
    # Remove only an identical unconditional DNS rule; keep conditional rules.
    rules = [r for r in copy.deepcopy(a.rules) if not (
        r.get("port") in (53, "53") and r.get("balancerTag") == POOL_A
        and r.get("network") in ("tcp,udp", "udp,tcp")
        and set(r) <= {"type", "port", "network", "balancerTag"}
    )]
    if not any(r.get("balancerTag") == POOL_A and r.get("network") in ("tcp,udp", "udp,tcp")
               and set(r) <= {"type", "network", "balancerTag"} for r in rules):
        rules.append({"type": "field", "network": "tcp,udp", "balancerTag": POOL_A})
    result["routing"] = {
        **copy.deepcopy(a.routing_options),
        "rules": _service_rules() + rules,
        "balancers": [
            {"tag": POOL_A, "selector": selectors_a, "strategy": {"type": "leastPing"}, "fallbackTag": TO_GUARD},
            {"tag": GUARD_A, "selector": selectors_a.copy(), "strategy": {"type": "roundRobin"}, "fallbackTag": TO_B},
            {"tag": POOL_B, "selector": selectors_b, "strategy": {"type": "leastPing"}, "fallbackTag": UNAVAILABLE},
        ],
    }
    result.pop("burstObservatory", None)
    result["observatory"] = {
        "subjectSelector": list(dict.fromkeys(selectors_a + selectors_b)),
        "probeUrl": probe_url, "probeInterval": interval, "enableConcurrency": True,
    }
    validate_allowlist_profile(result)
    return result


def compose_allowlist_balancer(
    payload: SubscriptionPayload, *, probe_url: str = DEFAULT_PROBE_URL,
    probe_interval: str = DEFAULT_PROBE_INTERVAL,
    profile_name: str = PROFILE_NAME, flag_code: str = "", description: str = "auto",
) -> SubscriptionPayload:
    """Replace one valid marked pair; preserve unrelated profiles and input.

    Missing/ambiguous/unsupported pairs stay separate with a diagnostic.
    A damaged already-composed graph raises instead of silently weakening it.
    """
    configs = payload if isinstance(payload, list) else [payload]
    marked: dict[str, list[tuple[int, dict[str, Any]]]] = {"A": [], "B": []}
    generated = False
    for index, config in enumerate(configs):
        if not isinstance(config, dict):
            continue
        if is_allowlist_profile(config):
            validate_allowlist_profile(config)
            generated = True
        roles = _roles(config.get("remarks"))
        if len(roles) > 1:
            logger.warning("allowlist balancer skipped: both role markers in one profile")
            return payload
        for role in roles:
            marked[role].append((index, config))
    if not marked["A"] and not marked["B"]:
        return payload
    if generated or len(marked["A"]) != 1 or len(marked["B"]) != 1:
        logger.warning("allowlist balancer skipped: expected exactly one marked A and one B")
        return payload
    _validate_probe(probe_url, probe_interval)
    label = format_profile_name(profile_name, flag_code)
    description = normalize_profile_description(description)
    ia, ca = marked["A"][0]
    ib, cb = marked["B"][0]
    try:
        composed = _build(_read_pool(ca), _read_pool(cb), probe_url, probe_interval, label, description)
    except InvalidPool as exc:
        logger.warning("allowlist balancer skipped: %s", exc)
        return payload
    logger.info("allowlist balancer composed from marked A/B profiles")
    return [composed if i == min(ia, ib) else config
            for i, config in enumerate(configs) if i not in {ia, ib} or i == min(ia, ib)]
