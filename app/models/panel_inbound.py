import copy
import json
from dataclasses import dataclass
from typing import Any

from app.models.inbound import (
    InboundDescriptor,
    compute_inbound_fingerprint,
    extract_transport_path,
)


@dataclass(frozen=True)
class PanelEndpoint:
    address: str
    port: int
    force_tls: str
    endpoint_index: int


def parse_json_field(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _resolve_default_address(inbound: dict[str, Any]) -> str:
    listen = str(inbound.get("listen", "")).strip()
    if listen and listen not in ("0.0.0.0", "::", ""):
        return listen

    share_addr = str(inbound.get("shareAddr", "")).strip()
    if share_addr:
        return share_addr

    return ""


def expand_panel_endpoints(inbound: dict[str, Any]) -> list[PanelEndpoint]:
    stream = parse_json_field(inbound.get("streamSettings"))
    external_proxies = stream.get("externalProxy")

    port_raw = inbound.get("port", 0)
    try:
        default_port = int(port_raw)
    except (TypeError, ValueError):
        default_port = 0

    default_dest = _resolve_default_address(inbound)

    if isinstance(external_proxies, list) and external_proxies:
        endpoints: list[PanelEndpoint] = []
        for index, item in enumerate(external_proxies):
            if not isinstance(item, dict):
                continue
            dest = str(item.get("dest", "")).strip() or default_dest
            port_value = item.get("port", default_port)
            try:
                port = int(port_value)
            except (TypeError, ValueError):
                port = default_port
            force_tls = str(item.get("forceTls", "same"))
            endpoints.append(
                PanelEndpoint(
                    address=dest,
                    port=port,
                    force_tls=force_tls,
                    endpoint_index=index,
                )
            )
        if endpoints:
            return endpoints

    return [
        PanelEndpoint(
            address=default_dest,
            port=default_port,
            force_tls="same",
            endpoint_index=0,
        )
    ]


def _apply_force_tls(stream: dict[str, Any], force_tls: str) -> dict[str, Any]:
    result = copy.deepcopy(stream)
    if force_tls == "tls":
        if result.get("security") != "tls":
            result["security"] = "tls"
            result["tlsSettings"] = {}
    elif force_tls == "none":
        if result.get("security") != "none":
            result["security"] = "none"
            result.pop("tlsSettings", None)
    return result


def endpoint_to_outbound(
    inbound: dict[str, Any],
    endpoint: PanelEndpoint,
) -> dict[str, Any]:
    protocol = str(inbound.get("protocol", ""))
    stream = parse_json_field(inbound.get("streamSettings"))
    stream.pop("externalProxy", None)
    stream = _apply_force_tls(stream, endpoint.force_tls)

    outbound: dict[str, Any] = {
        "protocol": protocol,
        "tag": "proxy",
        "streamSettings": stream,
        "settings": {
            "address": endpoint.address,
            "port": endpoint.port,
        },
    }
    return outbound


def panel_inbound_to_descriptors(inbound: dict[str, Any]) -> list[InboundDescriptor]:
    if inbound.get("enable") is False:
        return []

    panel_id_raw = inbound.get("id", 0)
    try:
        panel_inbound_id = int(panel_id_raw)
    except (TypeError, ValueError):
        panel_inbound_id = 0

    remark = str(inbound.get("remark", ""))
    endpoints = expand_panel_endpoints(inbound)
    descriptors: list[InboundDescriptor] = []

    for endpoint in endpoints:
        outbound = endpoint_to_outbound(inbound, endpoint)
        stream = outbound.get("streamSettings", {})
        if not isinstance(stream, dict):
            stream = {}
        settings = outbound.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}

        descriptors.append(
            InboundDescriptor(
                fingerprint=compute_inbound_fingerprint(outbound),
                remarks=remark,
                protocol=str(outbound.get("protocol", "")),
                network=str(stream.get("network", "")),
                address=str(settings.get("address", "")),
                path=extract_transport_path(stream),
                port=int(settings.get("port", 0) or 0),
                security=str(stream.get("security", "")),
                source_index=endpoint.endpoint_index,
                panel_inbound_id=panel_inbound_id,
                endpoint_index=endpoint.endpoint_index,
            )
        )

    return descriptors


def panel_inbounds_to_descriptors(inbounds: list[dict[str, Any]]) -> list[InboundDescriptor]:
    result: list[InboundDescriptor] = []
    for inbound in inbounds:
        result.extend(panel_inbound_to_descriptors(inbound))
    return result