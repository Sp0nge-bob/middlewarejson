from dataclasses import dataclass
from typing import Any

from app.models.inbound import compute_inbound_fingerprint


@dataclass
class ProxyNode:
    remarks: str
    protocol: str
    outbound: dict[str, Any]
    source_index: int
    tag: str = ""
    network: str = ""
    fingerprint: str = ""

    def with_tag(self, tag: str) -> "ProxyNode":
        tagged_outbound = {**self.outbound, "tag": tag}
        return ProxyNode(
            remarks=self.remarks,
            protocol=self.protocol,
            outbound=tagged_outbound,
            source_index=self.source_index,
            tag=tag,
            network=self.network,
            fingerprint=self.fingerprint,
        )


PROXY_TAGS = frozenset({"proxy"})


def extract_network(outbound: dict[str, Any]) -> str:
    stream = outbound.get("streamSettings")
    if isinstance(stream, dict):
        return str(stream.get("network", ""))
    if isinstance(stream, str):
        return ""
    return ""


def is_proxy_outbound(outbound: dict[str, Any]) -> bool:
    tag = outbound.get("tag", "")
    protocol = outbound.get("protocol", "")
    if tag in PROXY_TAGS:
        return True
    return protocol not in ("freedom", "blackhole", "dns")


def configs_to_nodes(configs: list[dict[str, Any]]) -> list[ProxyNode]:
    nodes: list[ProxyNode] = []
    for index, config in enumerate(configs):
        remarks = str(config.get("remarks", f"node-{index}"))
        outbounds = config.get("outbounds", [])
        if not isinstance(outbounds, list):
            continue
        for outbound in outbounds:
            if not isinstance(outbound, dict) or not is_proxy_outbound(outbound):
                continue
            nodes.append(
                ProxyNode(
                    remarks=remarks,
                    protocol=str(outbound.get("protocol", "")),
                    outbound=outbound,
                    source_index=index,
                    network=extract_network(outbound),
                    fingerprint=compute_inbound_fingerprint(outbound),
                )
            )
    return nodes