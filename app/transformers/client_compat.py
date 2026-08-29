"""Normalize 3x-ui JSON so HAPP / Xray-core can actually connect.

Sources:
- XTLS JSON subscription spec (array of complete client configs, socks then http)
- 3x-ui v3.7.0 json_service.go (strip sockopt / acceptProxyProtocol / xhttp server keys, flatten TLS)
- HAPP docs + MHSanaei/3x-ui#3718 (iOS/mac: socks before mixed; no localhost; fakedns without inbound)
- Xray routing: empty balancer selector blackholes the TUN
"""

from __future__ import annotations

import copy
from typing import Any

from app.models.subscription import SubscriptionPayload

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_SYSTEM_PROTOCOLS = frozenset({"freedom", "blackhole", "dns"})
_INBOUND_ORDER = {"socks": 0, "mixed": 1, "http": 2}
_XHTTP_SERVER_KEYS = (
    "noSSEHeader",
    "scMaxBufferedPosts",
    "scStreamUpServerSecs",
    "serverMaxHeaderBytes",
)
_ACCEPT_PROXY_NETWORKS = ("tcpSettings", "wsSettings", "httpupgradeSettings", "xhttpSettings")


def _as_list(payload: SubscriptionPayload) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _is_proxy_outbound(outbound: dict[str, Any]) -> bool:
    protocol = str(outbound.get("protocol", ""))
    tag = str(outbound.get("tag", ""))
    if tag == "proxy":
        return True
    return protocol not in _SYSTEM_PROTOCOLS and protocol != ""


def _proxy_outbounds(config: dict[str, Any]) -> list[dict[str, Any]]:
    outbounds = config.get("outbounds", [])
    if not isinstance(outbounds, list):
        return []
    return [
        item
        for item in outbounds
        if isinstance(item, dict) and _is_proxy_outbound(item)
    ]


def _proxy_address(outbound: dict[str, Any]) -> str:
    settings = outbound.get("settings")
    if not isinstance(settings, dict):
        return ""
    address = str(settings.get("address") or "").strip().lower()
    if address:
        return address
    for key in ("vnext", "servers"):
        block = settings.get(key)
        if isinstance(block, list) and block and isinstance(block[0], dict):
            return str(block[0].get("address") or "").strip().lower()
    return ""


def _flatten_security_settings(block: dict[str, Any]) -> None:
    nested = block.pop("settings", None)
    if not isinstance(nested, dict):
        return
    if not block.get("fingerprint") and nested.get("fingerprint"):
        block["fingerprint"] = nested["fingerprint"]
    for key in ("mldsa65Verify", "mldsa65Seed"):
        if nested.get(key) and not block.get(key):
            block[key] = nested[key]
    if nested.get("echConfigList") and not block.get("echConfigList"):
        block["echConfigList"] = nested["echConfigList"]


def _clean_stream_settings(stream: dict[str, Any]) -> dict[str, Any]:
    stream.pop("sockopt", None)
    stream.pop("externalProxy", None)

    for network_key in _ACCEPT_PROXY_NETWORKS:
        settings = stream.get(network_key)
        if isinstance(settings, dict):
            settings.pop("acceptProxyProtocol", None)
            if network_key == "wsSettings" and settings.get("heartbeatPeriod") == 0:
                settings.pop("heartbeatPeriod", None)

    tls = stream.get("tlsSettings")
    if isinstance(tls, dict):
        _flatten_security_settings(tls)

    reality = stream.get("realitySettings")
    if isinstance(reality, dict):
        _flatten_security_settings(reality)
        for key in ("mldsa65Verify", "mldsa65Seed"):
            if reality.get(key) == "":
                reality.pop(key, None)

    xhttp = stream.get("xhttpSettings")
    if isinstance(xhttp, dict):
        for key in _XHTTP_SERVER_KEYS:
            xhttp.pop(key, None)
        if str(xhttp.get("scMaxEachPostBytes") or "") in {"", "1000000"}:
            xhttp.pop("scMaxEachPostBytes", None)
        if str(xhttp.get("scMinPostsIntervalMs") or "") in {"", "30"}:
            xhttp.pop("scMinPostsIntervalMs", None)

    return stream


def _clean_outbound(outbound: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(outbound)
    stream = cleaned.get("streamSettings")
    if isinstance(stream, dict):
        cleaned["streamSettings"] = _clean_stream_settings(stream)

    if cleaned.get("protocol") == "freedom":
        settings = cleaned.get("settings")
        if isinstance(settings, dict) and settings.get("noises") == []:
            settings.pop("noises", None)
    return cleaned


def _clean_sniffing(inbound: dict[str, Any]) -> None:
    sniffing = inbound.get("sniffing")
    if not isinstance(sniffing, dict):
        return
    dest = sniffing.get("destOverride")
    if isinstance(dest, list):
        sniffing["destOverride"] = [item for item in dest if item != "fakedns"]


def _ensure_listen(inbound: dict[str, Any]) -> None:
    listen = str(inbound.get("listen") or "").strip()
    if listen in {"", "0.0.0.0", "::"}:
        inbound["listen"] = "127.0.0.1"


def _used_inbound_ports(inbounds: list[dict[str, Any]]) -> set[int]:
    ports: set[int] = set()
    for inbound in inbounds:
        try:
            ports.add(int(inbound.get("port") or 0))
        except (TypeError, ValueError):
            continue
    ports.discard(0)
    return ports


def _normalize_inbounds(config: dict[str, Any]) -> None:
    inbounds = config.get("inbounds")
    if not isinstance(inbounds, list) or not inbounds:
        return
    cleaned: list[dict[str, Any]] = []
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        item = copy.deepcopy(inbound)
        _ensure_listen(item)
        _clean_sniffing(item)
        cleaned.append(item)

    has_socks = any(item.get("protocol") == "socks" for item in cleaned)
    if not has_socks:
        used = _used_inbound_ports(cleaned)
        port = 10808 if 10808 not in used else (10807 if 10807 not in used else 20808)
        cleaned.insert(
            0,
            {
                "listen": "127.0.0.1",
                "port": port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True, "userLevel": 8},
                "tag": "socks",
            },
        )

    cleaned.sort(key=lambda item: _INBOUND_ORDER.get(str(item.get("protocol", "")), 9))
    config["inbounds"] = cleaned


def _clean_dns(config: dict[str, Any]) -> None:
    dns = config.get("dns")
    if not isinstance(dns, dict):
        return
    servers = dns.get("servers")
    if not isinstance(servers, list):
        return

    kept: list[Any] = []
    for server in servers:
        if isinstance(server, str):
            address = server.strip().lower()
        elif isinstance(server, dict):
            address = str(server.get("address") or "").strip().lower()
        else:
            kept.append(server)
            continue
        if address in _LOOPBACK:
            continue
        kept.append(server)

    if kept:
        dns["servers"] = kept
    else:
        config.pop("dns", None)


def _order_outbounds(config: dict[str, Any]) -> None:
    outbounds = config.get("outbounds")
    if not isinstance(outbounds, list):
        return
    proxies: list[dict[str, Any]] = []
    system: list[dict[str, Any]] = []
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        cleaned = _clean_outbound(outbound)
        if _is_proxy_outbound(cleaned):
            proxies.append(cleaned)
        else:
            system.append(cleaned)
    config["outbounds"] = proxies + system


def _balancer_is_dead(config: dict[str, Any]) -> bool:
    routing = config.get("routing")
    if not isinstance(routing, dict):
        return False
    balancers = routing.get("balancers")
    if not isinstance(balancers, list) or not balancers:
        return False
    for balancer in balancers:
        if not isinstance(balancer, dict):
            continue
        selector = balancer.get("selector")
        if isinstance(selector, list) and selector:
            return False
    proxies = _proxy_outbounds(config)
    return not proxies


def _is_loopback_only(config: dict[str, Any]) -> bool:
    proxies = _proxy_outbounds(config)
    if not proxies:
        return True
    return all(_proxy_address(item) in _LOOPBACK for item in proxies)


def _normalize_config(config: dict[str, Any]) -> dict[str, Any] | None:
    if _is_loopback_only(config):
        return None
    if _balancer_is_dead(config):
        return None

    normalized = copy.deepcopy(config)
    _order_outbounds(normalized)
    if not _proxy_outbounds(normalized):
        return None
    _normalize_inbounds(normalized)
    _clean_dns(normalized)
    return normalized


def normalize_for_client(payload: SubscriptionPayload) -> SubscriptionPayload:
    """Drop unusable profiles and strip fields that blackhole HAPP iOS TUN."""
    configs = _as_list(payload)
    if not configs:
        return payload

    normalized = [
        item for item in (_normalize_config(config) for config in configs) if item is not None
    ]
    if not normalized:
        return payload
    if isinstance(payload, list):
        return normalized
    return normalized[0]
