import logging

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.models.subscription import SubscriptionPayload
from app.services.profile_builder import build_balancer_rules
from app.services.rules_loader import load_rules
from app.services.transformer import PassthroughTransformer, SubscriptionTransformer
from app.transformers.rules_engine import RulesTransformer

logger = logging.getLogger(__name__)


class TransformService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._passthrough = PassthroughTransformer()
        self._yaml_transformer: SubscriptionTransformer | None = None
        self._repository = CatalogRepository(Database(settings.db_path))

        if settings.transform_mode == "rules":
            try:
                rules = load_rules(settings.rules_path)
                self._yaml_transformer = RulesTransformer(rules)
            except FileNotFoundError:
                logger.warning("rules file missing at %s", settings.rules_path)
            except Exception as exc:
                logger.error("failed to load rules from %s: %s", settings.rules_path, exc)

    def transform(self, sub_id: str, payload: SubscriptionPayload) -> SubscriptionPayload:
        if self._settings.transform_mode != "rules":
            return self._passthrough.transform(payload)

        group = self._repository.get_group_for_sub_id(sub_id)
        if not group:
            return self._passthrough.transform(payload)

        balancer_tag = self._repository.get_balancer_for_group(group)
        if not balancer_tag:
            return self._passthrough.transform(payload)

        db_rules = build_balancer_rules(self._repository, balancer_tag)
        if db_rules is not None:
            return RulesTransformer(db_rules).transform(payload)

        if self._yaml_transformer is not None:
            return self._yaml_transformer.transform(payload)

        return self._passthrough.transform(payload)