"""Normalize 3x-ui JSON subscriptions for HAPP import."""

from __future__ import annotations

import copy
import re
from typing import Any

from app.models.subscription import SubscriptionPayload

_LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "localhost", "::1"})
_UNSUPPORTED_STREAM_KEYS = frozenset({"finalmask"})
_SYSTEM_PROTOCOLS = frozenset({"freedom", "blackhole", "dns"})
_PADDING_RANGE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
_HAPP_STRIP_KEYS = frozenset({"inbounds", "dns", "policy", "stats", "log"})


def _as_config_list(payload: SubscriptionPayload) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    return [payload]


def _proxy_outbound(config: dict[str, Any]) -> dict[str, Any] | None:
    outbounds = config.get("outbounds", [])
    if not isinstance(outbounds, list):
        return None
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        protocol = str(outbound.get("protocol", ""))
        tag = str(outbound.get("tag", ""))
        if tag == "proxy" or protocol not in _SYSTEM_PROTOCOLS:
            return outbound
    return None


def _proxy_address(outbound: dict[str, Any]) -> str:
    settings = outbound.get("settings", {})
    if not isinstance(settings, dict):
        return ""
    return str(settings.get("address", "")).strip().lower()


def _nested_fingerprint(tls_settings: dict[str, Any]) -> str:
    nested = tls_settings.get("settings")
    if isinstance(nested, dict):
        return str(nested.get("fingerprint", ""))
    return ""


def _salamander_obfs(stream_settings: dict[str, Any]) -> dict[str, Any] | None:
    finalmask = stream_settings.get("finalmask")
    if not isinstance(finalmask, dict):
        return None
    udp_masks = finalmask.get("udp")
    if not isinstance(udp_masks, list):
        return None
    for mask in udp_masks:
        if not isinstance(mask, dict) or mask.get("type") != "salamander":
            continue
        settings = mask.get("settings")
        if not isinstance(settings, dict):
            continue
        password = settings.get("password")
        if password:
            return {"type": "salamander", "salamander": {"password": password}}
    return None


def _convert_hysteria_outbound(outbound: dict[str, Any]) -> dict[str, Any] | None:
    stream = outbound.get("streamSettings", {})
    if not isinstance(stream, dict):
        stream = {}
    settings = outbound.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}

    hysteria_settings = stream.get("hysteriaSettings", {})
    if not isinstance(hysteria_settings, dict):
        hysteria_settings = {}

    auth = hysteria_settings.get("auth") or settings.get("password")
    if not auth:
        return None

    address = settings.get("address")
    if not address:
        return None

    port_raw = settings.get("port", 443)
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 443

    tls = stream.get("tlsSettings", {})
    if not isinstance(tls, dict):
        tls = {}
    sni = str(tls.get("serverName", "")).strip()
    fingerprint = str(tls.get("fingerprint", "")).strip() or _nested_fingerprint(tls)
    alpn = tls.get("alpn")

    server: dict[str, Any] = {
        "address": address,
        "port": port,
        "password": auth,
    }
    if sni:
        server["sni"] = sni

    new_settings: dict[str, Any] = {"servers": [server]}
    obfs = _salamander_obfs(stream)
    if obfs:
        new_settings["obfs"] = obfs

    stream_out: dict[str, Any] = {"network": "tcp", "security": "tls"}
    tls_out: dict[str, Any] = {}
    if sni:
        tls_out["serverName"] = sni
    if fingerprint:
        tls_out["fingerprint"] = fingerprint
    if isinstance(alpn, list) and alpn:
        tls_out["alpn"] = alpn
    if tls_out:
        stream_out["tlsSettings"] = tls_out

    return {
        "tag": outbound.get("tag", "proxy"),
        "protocol": "hysteria2",
        "settings": new_settings,
        "streamSettings": stream_out,
    }


def _normalize_padding_bytes(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = _PADDING_RANGE.match(value)
    if not match:
        return value
    return int(match.group(1))


def _clean_stream_settings(stream_settings: dict[str, Any]) -> dict[str, Any]:
    stream = copy.deepcopy(stream_settings)
    for key in _UNSUPPORTED_STREAM_KEYS:
        stream.pop(key, None)

    tls = stream.get("tlsSettings")
    if isinstance(tls, dict):
        nested = tls.pop("settings", None)
        if isinstance(nested, dict) and not tls.get("fingerprint") and nested.get("fingerprint"):
            tls["fingerprint"] = nested["fingerprint"]

    reality = stream.get("realitySettings")
    if isinstance(reality, dict):
        reality.pop("mldsa65Verify", None)
        reality.pop("mldsa65Seed", None)
        nested = reality.get("settings")
        if isinstance(nested, dict):
            nested.pop("mldsa65Verify", None)

    xhttp = stream.get("xhttpSettings")
    if isinstance(xhttp, dict) and "xPaddingBytes" in xhttp:
        xhttp["xPaddingBytes"] = _normalize_padding_bytes(xhttp["xPaddingBytes"])

    return stream


def _clean_system_outbound(outbound: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(outbound)
    if cleaned.get("protocol") != "freedom":
        return cleaned
    settings = cleaned.get("settings")
    if isinstance(settings, dict):
        settings.pop("noises", None)
    return cleaned


def _strip_happ_boilerplate(config: dict[str, Any]) -> None:
    for key in _HAPP_STRIP_KEYS:
        config.pop(key, None)


def _sanitize_outbound(outbound: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(outbound, dict):
        return None

    protocol = str(outbound.get("protocol", ""))
    if protocol == "hysteria":
        return _convert_hysteria_outbound(outbound)

    cleaned = copy.deepcopy(outbound)
    stream = cleaned.get("streamSettings")
    if isinstance(stream, dict):
        cleaned["streamSettings"] = _clean_stream_settings(stream)
    return cleaned


def _sanitize_config(config: dict[str, Any]) -> dict[str, Any] | None:
    proxy = _proxy_outbound(config)
    if proxy is None:
        return None

    if _proxy_address(proxy) in _LOOPBACK_ADDRESSES:
        return None

    sanitized = copy.deepcopy(config)
    outbounds = sanitized.get("outbounds", [])
    if not isinstance(outbounds, list):
        return None

    new_outbounds: list[dict[str, Any]] = []
    has_proxy = False
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        protocol = str(outbound.get("protocol", ""))
        tag = str(outbound.get("tag", ""))
        if tag == "proxy" or protocol not in _SYSTEM_PROTOCOLS:
            converted = _sanitize_outbound(outbound)
            if converted is None:
                return None
            new_outbounds.append(converted)
            has_proxy = True
            continue
        new_outbounds.append(_clean_system_outbound(outbound))

    if not has_proxy:
        return None

    sanitized["outbounds"] = new_outbounds
    _strip_happ_boilerplate(sanitized)
    return sanitized


def sanitize_for_happ(payload: SubscriptionPayload) -> SubscriptionPayload:
    configs = _as_config_list(payload)
    sanitized = [_item for item in configs if (_item := _sanitize_config(item)) is not None]
    if not sanitized:
        return payload
    if isinstance(payload, list):
        return sanitized
    return sanitized[0]