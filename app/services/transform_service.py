import logging

from app.config import Settings
from app.db.database import Database
from app.db.repository import SettingsRepository
from app.features.allowlist_balancer import compose_allowlist_balancer
from app.models.subscription import SubscriptionPayload
from app.services.mode import TRANSFORM_MODE_KEY, resolve_transform_mode
from app.services.feature_settings import (
    ALLOWLIST_BALANCER_KEY, ALLOWLIST_BALANCER_NAME_KEY, ALLOWLIST_BALANCER_FLAG_KEY,
    resolve_allowlist_balancer, resolve_allowlist_name, resolve_allowlist_flag,
    ALLOWLIST_BALANCER_DESCRIPTION_KEY, resolve_allowlist_description,
)
from app.services.transformer import PassthroughTransformer
from app.transformers.ios_fix import apply_ios_fix, apply_ios_fix_dns

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
        if resolve_allowlist_balancer(
            self._settings, self._repository.get_setting(ALLOWLIST_BALANCER_KEY),
        ):
            raw = compose_allowlist_balancer(
                raw, probe_url=self._settings.allowlist_probe_url,
                probe_interval=f"{self._settings.allowlist_probe_interval_sec:g}s",
                profile_name=resolve_allowlist_name(
                    self._settings, self._repository.get_setting(ALLOWLIST_BALANCER_NAME_KEY),
                ),
                flag_code=resolve_allowlist_flag(
                    self._settings, self._repository.get_setting(ALLOWLIST_BALANCER_FLAG_KEY),
                ),
                description=resolve_allowlist_description(
                    self._settings, self._repository.get_setting(ALLOWLIST_BALANCER_DESCRIPTION_KEY),
                ),
            )
        if mode == "ios-fix":
            logger.info("ios-fix for sub_id=%s", sub_id)
            return apply_ios_fix(raw)
        if mode == "ios-fix-dns":
            logger.info("ios-fix-dns for sub_id=%s", sub_id)
            return apply_ios_fix_dns(raw)
        logger.info("passthrough for sub_id=%s", sub_id)
        return raw
