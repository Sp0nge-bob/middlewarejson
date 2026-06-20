import re
from typing import Any
from urllib.parse import urlparse

SUB_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")

SubscriptionPayload = dict[str, Any] | list[dict[str, Any]]


def validate_sub_id(sub_id: str) -> bool:
    return bool(SUB_ID_PATTERN.match(sub_id))


def parse_subscription_reference(value: str) -> str:
    """Извлечь sub_id из ссылки на JSON-подписку или из самого sub_id."""
    raw = value.strip()
    if not raw:
        raise ValueError("Пустое значение")

    if validate_sub_id(raw):
        return raw

    parsed = urlparse(raw)
    if not parsed.scheme and not parsed.netloc:
        raise ValueError(
            "Укажите ссылку на JSON-подписку, например "
            "https://example.com/<json-path>/<sub_id>"
        )

    path = parsed.path.rstrip("/")
    candidate = path.rsplit("/", 1)[-1]
    if validate_sub_id(candidate):
        return candidate

    raise ValueError(
        "Не удалось извлечь sub_id. Пример: "
        "https://example.com/<json-path>/<sub_id>"
    )


def validate_payload(payload: SubscriptionPayload) -> None:
    configs = payload if isinstance(payload, list) else [payload]
    if not configs:
        raise ValueError("empty subscription payload")

    for config in configs:
        if not isinstance(config, dict):
            raise ValueError("subscription item must be an object")
        outbounds = config.get("outbounds")
        if not isinstance(outbounds, list):
            raise ValueError("missing or invalid outbounds array")