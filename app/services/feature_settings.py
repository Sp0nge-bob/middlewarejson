"""Feature switches are independent of TRANSFORM_MODE."""

import logging

from app.config import Settings
from app.features.allowlist_balancer import (
    normalize_profile_name, normalize_profile_flag, normalize_profile_description,
)

logger = logging.getLogger(__name__)
ALLOWLIST_BALANCER_KEY = "allowlist_balancer_enabled"
ALLOWLIST_BALANCER_NAME_KEY = "allowlist_balancer_name"
ALLOWLIST_BALANCER_FLAG_KEY = "allowlist_balancer_flag"
ALLOWLIST_BALANCER_DESCRIPTION_KEY = "allowlist_balancer_description"


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


def resolve_allowlist_name(settings: Settings, repository_value: str | None) -> str:
    if repository_value is None:
        return settings.allowlist_balancer_name
    try:
        return normalize_profile_name(repository_value)
    except ValueError:
        logger.warning("invalid allowlist profile name; using configured default")
        return settings.allowlist_balancer_name


def resolve_allowlist_flag(settings: Settings, repository_value: str | None) -> str:
    if repository_value is None:
        return settings.allowlist_balancer_flag
    try:
        return normalize_profile_flag(repository_value)
    except ValueError:
        logger.warning("invalid allowlist profile flag; using configured default")
        return settings.allowlist_balancer_flag


def resolve_allowlist_description(settings: Settings, repository_value: str | None) -> str:
    if repository_value is None:
        return settings.allowlist_balancer_description
    try:
        return normalize_profile_description(repository_value)
    except ValueError:
        logger.warning("invalid allowlist profile description; using configured default")
        return settings.allowlist_balancer_description
