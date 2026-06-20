from dataclasses import dataclass
from typing import Any


def _get_nested(data: dict[str, Any], *keys: str, default: str = "") -> str:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    if current is None:
        return default
    return str(current)


def extract_transport_path(stream: dict[str, Any]) -> str:
    return (
        _get_nested(stream, "wsSettings", "path")
        or _get_nested(stream, "xhttpSettings", "path")
        or _get_nested(stream, "grpcSettings", "serviceName")
    )


def compute_inbound_fingerprint(outbound: dict[str, Any]) -> str:
    protocol = str(outbound.get("protocol", ""))
    settings = outbound.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}

    stream = outbound.get("streamSettings", {})
    if not isinstance(stream, dict):
        stream = {}

    address = str(settings.get("address", ""))
    port = str(settings.get("port", ""))
    network = str(stream.get("network", ""))
    security = str(stream.get("security", ""))
    path = extract_transport_path(stream)
    mode = _get_nested(stream, "xhttpSettings", "mode")

    return f"{protocol}|{address}|{network}|{path}|{port}|{security}|{mode}"


@dataclass
class InboundDescriptor:
    fingerprint: str
    remarks: str
    protocol: str
    network: str
    address: str
    path: str
    port: int
    security: str
    source_index: int
    panel_inbound_id: int = 0
    endpoint_index: int = 0

    @classmethod
    def from_config(cls, index: int, config: dict[str, Any]) -> "InboundDescriptor | None":
        remarks = str(config.get("remarks", f"node-{index}"))
        outbounds = config.get("outbounds", [])
        if not isinstance(outbounds, list):
            return None

        proxy = None
        for outbound in outbounds:
            if not isinstance(outbound, dict):
                continue
            tag = outbound.get("tag", "")
            protocol = outbound.get("protocol", "")
            if tag == "proxy" or protocol not in ("freedom", "blackhole", "dns", None, ""):
                proxy = outbound
                break

        if proxy is None:
            return None

        stream = proxy.get("streamSettings", {})
        if not isinstance(stream, dict):
            stream = {}

        settings = proxy.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}

        port_raw = settings.get("port", 0)
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            port = 0

        return cls(
            fingerprint=compute_inbound_fingerprint(proxy),
            remarks=remarks,
            protocol=str(proxy.get("protocol", "")),
            network=str(stream.get("network", "")),
            address=str(settings.get("address", "")),
            path=extract_transport_path(stream),
            port=port,
            security=str(stream.get("security", "")),
            source_index=index,
        )