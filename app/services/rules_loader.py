import logging
from pathlib import Path

import yaml

from app.models.rules_schema import TransformRules

logger = logging.getLogger(__name__)


def load_rules(path: str | Path) -> TransformRules:
    rules_path = Path(path)
    if not rules_path.is_file():
        raise FileNotFoundError(f"rules file not found: {rules_path}")

    with rules_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    return TransformRules.from_dict(data)