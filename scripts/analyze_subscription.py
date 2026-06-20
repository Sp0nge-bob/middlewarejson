#!/usr/bin/env python3
"""Анализ JSON-подписки 3x-ui: уникальные поля для rules.yaml."""
import json
import sys
from pathlib import Path
from typing import Any


def _get(d: dict, *keys: str, default: Any = "") -> Any:
    cur: Any = d
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key, default)
    return cur


def analyze_config(index: int, config: dict[str, Any]) -> dict[str, Any]:
    proxy = next(
        (
            o
            for o in config.get("outbounds", [])
            if isinstance(o, dict) and o.get("tag") == "proxy"
            or o.get("protocol") not in ("freedom", "blackhole", None)
        ),
        {},
    )
    stream = proxy.get("streamSettings", {})
    if isinstance(stream, str):
        stream = {}

    row = {
        "index": index,
        "remarks": config.get("remarks", ""),
        "protocol": proxy.get("protocol", ""),
        "network": stream.get("network", ""),
        "security": stream.get("security", ""),
        "address": _get(proxy, "settings", "address"),
        "port": _get(proxy, "settings", "port"),
        "client_id": _get(proxy, "settings", "id"),
        "flow": _get(proxy, "settings", "flow"),
        "path": (
            _get(stream, "wsSettings", "path")
            or _get(stream, "xhttpSettings", "path")
            or _get(stream, "grpcSettings", "serviceName")
            or ""
        ),
        "xhttp_mode": _get(stream, "xhttpSettings", "mode"),
        "fingerprint": _get(stream, "tlsSettings", "fingerprint")
        or _get(stream, "realitySettings", "fingerprint"),
        "reality_sni": _get(stream, "realitySettings", "serverName"),
        "tls_server_name": _get(stream, "tlsSettings", "serverName"),
    }
    return row


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if source:
        data = json.loads(source.read_text(encoding="utf-8"))
    else:
        data = json.load(sys.stdin)

    configs = data if isinstance(data, list) else [data]
    rows = [analyze_config(i, c) for i, c in enumerate(configs)]

    print(f"configs: {len(rows)}\n")
    print(
        f"{'#':<3} {'remarks':<22} {'proto':<8} {'net':<8} {'address':<28} {'path/service':<20} unique?"
    )
    print("-" * 110)

    fields = [
        "remarks",
        "protocol",
        "network",
        "security",
        "address",
        "port",
        "client_id",
        "flow",
        "path",
        "xhttp_mode",
        "fingerprint",
    ]
    unique_counts = {f: len({r[f] for r in rows if r[f]}) for f in fields}

    for r in rows:
        print(
            f"{r['index']:<3} {str(r['remarks'])[:22]:<22} {r['protocol']:<8} {r['network']:<8} "
            f"{str(r['address'])[:28]:<28} {str(r['path'])[:20]:<20}"
        )

    print("\n=== Уникальность полей (число разных значений) ===")
    for field, count in sorted(unique_counts.items(), key=lambda x: -x[1]):
        useful = "✓ для match" if count > 1 and field != "client_id" else ("✗ общий" if count <= 1 else "")
        print(f"  {field:<14} {count:>2} значений  {useful}")

    print("\n=== Чего НЕТ в JSON 3x-ui ===")
    print("  inbound_id / panel_id — не экспортируется")
    print("  outbound tag — всегда 'proxy' в сыром JSON")
    print("  client UUID (settings.id) — один на всю подписку")


if __name__ == "__main__":
    main()