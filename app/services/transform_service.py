import logging

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.models.subscription import SubscriptionPayload
from app.services.panel_api import TRANSFORM_MODE_KEY, resolve_transform_mode
from app.services.profile_builder import build_balancer_rules
from app.services.transformer import PassthroughTransformer
from app.transformers.client_compat import normalize_for_client
from app.transformers.ios_fix import apply_ios_fix
from app.transformers.rules_engine import RulesTransformer

logger = logging.getLogger(__name__)


class TransformService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._passthrough = PassthroughTransformer()
        self._repository = CatalogRepository(Database(settings.db_path))

    def _resolved_mode(self) -> str:
        return resolve_transform_mode(
            self._settings,
            self._repository.get_setting(TRANSFORM_MODE_KEY),
        )

    def transform(self, sub_id: str, payload: SubscriptionPayload) -> SubscriptionPayload:
        mode = self._resolved_mode()
        if mode == "ios-fix":
            logger.info("ios-fix for sub_id=%s: first inbound mixed → socks", sub_id)
            return apply_ios_fix(self._passthrough.transform(payload))
        if mode != "rules":
            logger.info(
                "transform skipped for sub_id=%s: TRANSFORM_MODE=%s (need rules)",
                sub_id,
                mode,
            )
            return normalize_for_client(self._passthrough.transform(payload))

        balancer_tags = self._repository.get_balancer_tags_for_sub_id(sub_id)
        if not balancer_tags:
            group_name = self._repository.get_group_for_sub_id(sub_id)
            logger.info(
                "transform skipped for sub_id=%s: no balancers (client group=%s)",
                sub_id,
                group_name or "not in index",
            )
            return normalize_for_client(self._passthrough.transform(payload))

        db_rules = build_balancer_rules(self._repository, balancer_tags)
        if db_rules is None:
            logger.warning(
                "balancers %s are missing or empty, passthrough for sub_id=%s",
                balancer_tags,
                sub_id,
            )
            return normalize_for_client(self._passthrough.transform(payload))

        logger.info(
            "transform rules for sub_id=%s: balancers=%s",
            sub_id,
            balancer_tags,
        )
        return normalize_for_client(RulesTransformer(db_rules).transform(payload))