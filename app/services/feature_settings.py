"""Feature switches are independent of TRANSFORM_MODE."""

import logging

from app.config import Settings

logger = logging.getLogger(__name__)
ALLOWLIST_BALANCER_KEY = "allowlist_balancer_enabled"


def normalize_feature_switch(value: str) -> bool:
    value = value.strip().lower()
    if value in {"on", "true", "1", "yes"}:
        return True
    if value in {"off", "false", "0", "no"}:
        return False
    raise ValueError("значение должно быть on или off")


def resolve_allowlist_balancer(settings: Settings, repository_value: str | None) -> bool:
    if repository_value is None or not repository_value.strip():
        return settings.allowlist_balancer_enabled
    try:
        return normalize_feature_switch(repository_value)
    except ValueError:
        logger.warning("invalid allowlist balancer switch; feature disabled")
        return False
