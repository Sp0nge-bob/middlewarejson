import logging
from typing import Any

from app.config import Settings
from app.db.repository import CatalogRepository
from app.models.inbound import InboundDescriptor
from app.models.panel_inbound import panel_inbounds_to_descriptors
from app.services.panel_api import (
    PANEL_API_BASE_URL_KEY,
    PANEL_API_TOKEN_KEY,
    PANEL_WEB_BASE_PATH_KEY,
    PanelApiClient,
    PanelApiError,
    resolve_panel_base_url,
    resolve_panel_token,
    resolve_panel_web_base_path,
)

logger = logging.getLogger(__name__)


def configs_to_inbounds(configs: list[dict[str, Any]]) -> list[InboundDescriptor]:
    inbounds: list[InboundDescriptor] = []
    for index, config in enumerate(configs):
        descriptor = InboundDescriptor.from_config(index, config)
        if descriptor is not None:
            inbounds.append(descriptor)
    return inbounds


def fetch_panel_inbounds_sync(settings: Settings, repository: CatalogRepository) -> list[dict[str, Any]]:
    token = resolve_panel_token(settings, repository.get_setting(PANEL_API_TOKEN_KEY))
    web_path = resolve_panel_web_base_path(
        settings,
        repository.get_setting(PANEL_WEB_BASE_PATH_KEY),
    )
    base_url = resolve_panel_base_url(
        settings,
        repository.get_setting(PANEL_API_BASE_URL_KEY),
    )
    client = PanelApiClient(
        settings,
        token,
        web_base_path=web_path,
        api_base_url=base_url,
    )
    return client.fetch_inbounds_list()


def sync_catalog(settings: Settings, repository: CatalogRepository) -> dict[str, int | str]:
    try:
        inbounds_raw = fetch_panel_inbounds_sync(settings, repository)
    except PanelApiError as exc:
        raise ValueError(str(exc)) from exc

    descriptors = panel_inbounds_to_descriptors(inbounds_raw)
    upserted, deactivated = repository.upsert_inbounds(descriptors)

    logger.info(
        "catalog sync complete: panel_inbounds=%s upserted=%s deactivated=%s",
        len(inbounds_raw),
        upserted,
        deactivated,
    )
    return {
        "panel_inbounds": len(inbounds_raw),
        "upserted": upserted,
        "deactivated": deactivated,
        "total_active": len(descriptors),
    }