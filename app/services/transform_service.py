import logging

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.models.subscription import SubscriptionPayload
from app.services.profile_builder import build_balancer_rules
from app.services.transformer import PassthroughTransformer
from app.transformers.rules_engine import RulesTransformer

logger = logging.getLogger(__name__)


class TransformService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._passthrough = PassthroughTransformer()
        self._repository = CatalogRepository(Database(settings.db_path))

    def transform(self, sub_id: str, payload: SubscriptionPayload) -> SubscriptionPayload:
        mode = self._settings.transform_mode.strip().lower()
        if mode != "rules":
            logger.info(
                "transform skipped for sub_id=%s: TRANSFORM_MODE=%s (need rules)",
                sub_id,
                self._settings.transform_mode,
            )
            return self._passthrough.transform(payload)

        balancer_tags = self._repository.get_balancer_tags_for_sub_id(sub_id)
        if not balancer_tags:
            group_name = self._repository.get_group_for_sub_id(sub_id)
            logger.info(
                "transform skipped for sub_id=%s: no balancers (client group=%s)",
                sub_id,
                group_name or "not in index",
            )
            return self._passthrough.transform(payload)

        db_rules = build_balancer_rules(self._repository, balancer_tags)
        if db_rules is None:
            logger.warning(
                "balancers %s are missing or empty, passthrough for sub_id=%s",
                balancer_tags,
                sub_id,
            )
            return self._passthrough.transform(payload)

        logger.info(
            "transform rules for sub_id=%s: balancers=%s",
            sub_id,
            balancer_tags,
        )
        return RulesTransformer(db_rules).transform(payload)