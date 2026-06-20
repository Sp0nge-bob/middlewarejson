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
        if self._settings.transform_mode != "rules":
            return self._passthrough.transform(payload)

        balancer_tag = self._repository.get_balancer_tag_for_sub_id(sub_id)
        if not balancer_tag:
            return self._passthrough.transform(payload)

        db_rules = build_balancer_rules(self._repository, balancer_tag)
        if db_rules is None:
            logger.warning(
                "balancer '%s' is missing or empty, passthrough for sub_id=%s",
                balancer_tag,
                sub_id,
            )
            return self._passthrough.transform(payload)

        return RulesTransformer(db_rules).transform(payload)