#!/usr/bin/env python3
"""Find fields in 3x-ui JSON subscription that HAPP likely rejects."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# HAPP docs: VLESS, VMess, SS, Socks5, Trojan, Hysteria2 — not raw Xray 26 extras.
HAPP_PROTOCOLS = frozenset({"vless", "vmess", "shadowsocks", "socks", "trojan", "hysteria2"})
HAPP_NETWORKS = frozenset({"tcp", "ws", "grpc", "http", "h2", "quic", "kcp", "mkcp"})

_PADDING_RANGE = re.compile(r"^\d+\s*-\s*\d+$")


def _walk(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else key
            found.append((child, value))
            found.extend(_walk(value, child))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            child = f"{path}[{index}]"
            found.extend(_walk(value, child))
    return found


def _proxy_outbound(config: dict[str, Any]) -> dict[str, Any] | None:
    for outbound in config.get("outbounds", []):
        if not isinstance(outbound, dict):
            continue
        if outbound.get("tag") == "proxy" or outbound.get("protocol") not in (
            "freedom",
            "blackhole",
            "dns",
        ):
            return outbound
    return None


def _check_config(index: int, config: dict[str, Any]) -> list[dict[str, str]]:
    remarks = str(config.get("remarks", f"#{index}"))
    issues: list[dict[str, str]] = []
    proxy = _proxy_outbound(config)
    if proxy is None:
        issues.append({"severity": "critical", "field": "outbounds", "reason": "нет proxy outbound"})
        return issues

    protocol = str(proxy.get("protocol", ""))
    if protocol and protocol not in HAPP_PROTOCOLS:
        issues.append(
            {
                "severity": "critical",
                "field": "outbounds[].protocol",
                "reason": f'"{protocol}" — HAPP знает только {sorted(HAPP_PROTOCOLS)}',
            }
        )

    settings = proxy.get("settings", {})
    if isinstance(settings, dict):
        address = str(settings.get("address", "")).lower()
        if address in {"127.0.0.1", "localhost", "::1"}:
            issues.append(
                {
                    "severity": "critical",
                    "field": "outbounds[].settings.address",
                    "reason": f'"{address}" — localhost недоступен с телефона',
                }
            )

    stream = proxy.get("streamSettings", {})
    if isinstance(stream, dict):
        network = str(stream.get("network", ""))
        if network and network not in HAPP_NETWORKS:
            issues.append(
                {
                    "severity": "critical",
                    "field": "streamSettings.network",
                    "reason": f'"{network}" — нестандартный transport для HAPP JSON',
                }
            )

        if "finalmask" in stream:
            issues.append(
                {
                    "severity": "critical",
                    "field": "streamSettings.finalmask",
                    "reason": "поле Xray 26.x — в HAPP docs нет, парсер не знает",
                }
            )

        xhttp = stream.get("xhttpSettings")
        if isinstance(xhttp, dict):
            padding = xhttp.get("xPaddingBytes")
            if isinstance(padding, str) and _PADDING_RANGE.match(padding.strip()):
                issues.append(
                    {
                        "severity": "high",
                        "field": "xhttpSettings.xPaddingBytes",
                        "reason": f'"{padding}" — строка-диапазон, ожидается число',
                    }
                )

        tls = stream.get("tlsSettings")
        if isinstance(tls, dict) and isinstance(tls.get("settings"), dict):
            issues.append(
                {
                    "severity": "medium",
                    "field": "tlsSettings.settings",
                    "reason": "вложенный объект settings — дубль fingerprint, нестандартно",
                }
            )

        reality = stream.get("realitySettings")
        if isinstance(reality, dict):
            for key in ("mldsa65Verify", "mldsa65Seed"):
                if key in reality:
                    issues.append(
                        {
                            "severity": "high",
                            "field": f"realitySettings.{key}",
                            "reason": "поле Xray 26.x (ML-DSA) — HAPP не документирует",
                        }
                    )

    for path, value in _walk(config):
        base = path.rsplit(".", 1)[-1]
        if base == "fakedns" or value == "fakedns":
            issues.append(
                {
                    "severity": "medium",
                    "field": path,
                    "reason": "fakedns в sniffing — не все клиенты поддерживают",
                }
            )
        if base == "noises" and value == []:
            issues.append(
                {
                    "severity": "low",
                    "field": path,
                    "reason": "пустой noises[] в freedom outbound",
                }
            )
        if base == "heartbeatPeriod" and value == 0:
            issues.append(
                {
                    "severity": "low",
                    "field": path,
                    "reason": "heartbeatPeriod: 0",
                }
            )

    routing = config.get("routing")
    balancers = routing.get("balancers") if isinstance(routing, dict) else None
    if isinstance(balancers, list):
        has_observatory = "observatory" in config or "burstObservatory" in config
        if isinstance(routing, dict):
            has_observatory = has_observatory or "observatory" in routing or "burstObservatory" in routing
        for b_index, balancer in enumerate(balancers):
            if not isinstance(balancer, dict):
                continue
            strategy = balancer.get("strategy")
            stype = ""
            if isinstance(strategy, dict):
                stype = str(strategy.get("type") or "")
            elif isinstance(strategy, str):
                stype = strategy
            stype_l = stype.lower()
            fallback = str(balancer.get("fallbackTag") or "").strip()
            if fallback and stype_l in {"", "random", "roundrobin"}:
                issues.append(
                    {
                        "severity": "critical",
                        "field": f"routing.balancers[{b_index}].fallbackTag",
                        "reason": (
                            f'{stype or "random"} + fallbackTag="{fallback}" без observatory — '
                            "Xray RequireFeatures(Observatory), "
                            "«core: not all dependencies are resolved» (3x-ui#2724)"
                        )
                        if not has_observatory
                        else (
                            f'{stype or "random"} + fallbackTag регистрирует Observatory '
                            "(Xray-core balancing.go InjectContext)"
                        ),
                    }
                )
            if stype_l in {"leastping", "leastload"}:
                has_burst = "burstObservatory" in config or (
                    isinstance(routing, dict) and "burstObservatory" in routing
                )
                has_obs = "observatory" in config or (
                    isinstance(routing, dict) and "observatory" in routing
                )
                if has_burst or not has_obs:
                    issues.append(
                        {
                            "severity": "high",
                            "field": f"routing.balancers[{b_index}].strategy.type",
                            "reason": (
                                f"{stype} на iPhone нужен top-level observatory, "
                                "не burstObservatory (Xray #3058, 3x-ui JSON sub)"
                            ),
                        }
                    )
                if not fallback:
                    issues.append(
                        {
                            "severity": "high",
                            "field": f"routing.balancers[{b_index}].fallbackTag",
                            "reason": "leastPing без fallbackTag до первой пробы не выбирает outbound",
                        }
                    )

    return issues


def diagnose(payload: list[dict[str, Any]]) -> None:
    print(f"Профилей в массиве: {len(payload)}\n")

    all_critical_profiles: list[str] = []
    for index, config in enumerate(payload):
        issues = _check_config(index, config)
        remarks = str(config.get("remarks", f"#{index}"))
        if not issues:
            print(f"[{index}] {remarks}")
            print("  OK — явных проблем не найдено\n")
            continue

        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        issues.sort(key=lambda item: severity_order.get(item["severity"], 9))
        has_critical = any(item["severity"] == "critical" for item in issues)
        if has_critical:
            all_critical_profiles.append(remarks)

        print(f"[{index}] {remarks}")
        for issue in issues:
            print(f"  [{issue['severity']}] {issue['field']}: {issue['reason']}")
        print()

    print("=== ВЫВОД ===")
    if all_critical_profiles:
        print("Профили с КРИТИЧЕСКИМИ проблемами (скорее всего ломают весь массив):")
        for name in all_critical_profiles:
            print(f"  - {name}")
        print()
        print("Тест в HAPP: импортируйте массив БЕЗ этих профилей.")
        print("В 3x-ui: снимите галочку у клиента для этих инбаундов.")
    else:
        print("Критических полей нет — ищите проблему в заголовках ответа или версии HAPP.")

    print()
    print("=== Заголовки ответа (из вашего curl) ===")
    print("Content-Type: text/plain — тело JSON валидно, но тип не application/json")
    print("HAPP при импорте по URL может ожидать application/json")


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if source:
        raw = source.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    # обрезать мусор после JSON (как " проверяй")
    raw = raw.strip()
    if not raw.startswith("["):
        start = raw.find("[")
        if start >= 0:
            raw = raw[start:]
    end = raw.rfind("]")
    if end >= 0:
        raw = raw[: end + 1]

    payload = json.loads(raw)
    if not isinstance(payload, list):
        payload = [payload]
    diagnose(payload)


if __name__ == "__main__":
    main()