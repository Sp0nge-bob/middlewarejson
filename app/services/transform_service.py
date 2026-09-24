import logging

from app.config import Settings
from app.db.database import Database
from app.db.repository import SettingsRepository
from app.models.subscription import SubscriptionPayload
from app.services.mode import TRANSFORM_MODE_KEY, resolve_transform_mode
from app.services.transformer import PassthroughTransformer
from app.transformers.ios_fix import apply_ios_fix, apply_ios_fix_beta

logger = logging.getLogger(__name__)


class TransformService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._passthrough = PassthroughTransformer()
        self._repository = SettingsRepository(Database(settings.db_path))

    def _resolved_mode(self) -> str:
        return resolve_transform_mode(
            self._settings,
            self._repository.get_setting(TRANSFORM_MODE_KEY),
        )

    def transform(self, sub_id: str, payload: SubscriptionPayload) -> SubscriptionPayload:
        mode = self._resolved_mode()
        raw = self._passthrough.transform(payload)
        if mode == "ios-fix":
            logger.info("ios-fix for sub_id=%s", sub_id)
            return apply_ios_fix(raw)
        if mode == "ios-fix-beta":
            logger.info("ios-fix-beta for sub_id=%s", sub_id)
            return apply_ios_fix_beta(raw)
        logger.info("passthrough for sub_id=%s", sub_id)
        return raw
