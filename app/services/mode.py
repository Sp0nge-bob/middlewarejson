import logging

from app.config import Settings

logger = logging.getLogger(__name__)

TRANSFORM_MODE_KEY = "transform_mode"
VALID_TRANSFORM_MODES = frozenset({"passthrough", "ios-fix", "ios-fix-beta"})


def normalize_transform_mode(value: str) -> str:
    mode = value.strip().lower().replace("_", "-")
    if mode in ("iosfix", "ios-fix"):
        mode = "ios-fix"
    elif mode in ("iosfixbeta", "ios-fix-beta", "iosfix-beta"):
        mode = "ios-fix-beta"
    if mode not in VALID_TRANSFORM_MODES:
        raise ValueError(
            f"режим должен быть passthrough, ios-fix или ios-fix-beta, получено: {value!r}"
        )
    return mode


def resolve_transform_mode(
    settings: Settings,
    repository_value: str | None,
) -> str:
    raw = repository_value if repository_value and repository_value.strip() else settings.transform_mode
    try:
        return normalize_transform_mode(raw)
    except ValueError:
        logger.warning("unknown TRANSFORM_MODE %r, falling back to passthrough", raw)
        return "passthrough"
