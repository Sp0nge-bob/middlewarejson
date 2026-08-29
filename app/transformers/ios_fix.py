"""iOS-FIX: passthrough, but first inbound mixed → socks (HAPP iPhone issue)."""

from __future__ import annotations

import copy
from typing import Any

from app.models.subscription import SubscriptionPayload


def apply_ios_fix(payload: SubscriptionPayload) -> SubscriptionPayload:
    configs = payload if isinstance(payload, list) else [payload]
    result: list[Any] = []
    for config in configs:
        if not isinstance(config, dict):
            result.append(config)
            continue
        fixed = copy.deepcopy(config)
        inbounds = fixed.get("inbounds")
        if isinstance(inbounds, list) and inbounds:
            first = inbounds[0]
            if isinstance(first, dict) and str(first.get("protocol", "")).strip().lower() == "mixed":
                first["protocol"] = "socks"
        result.append(fixed)
    if isinstance(payload, list):
        return result
    return result[0] if result else payload
