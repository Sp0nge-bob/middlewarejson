import logging
from typing import Any

from app.config import Settings
from app.db.repository import CatalogRepository, ClientRecord
from app.services.panel_api import (
    PANEL_WEB_BASE_PATH_KEY,
    PanelApiClient,
    PanelApiError,
    resolve_panel_token,
    resolve_panel_web_base_path,
)

logger = logging.getLogger(__name__)


def _client_from_panel_row(row: dict[str, Any]) -> ClientRecord | None:
    if row.get("enable") is False:
        return None

    sub_id = str(row.get("subId") or row.get("sub_id") or "").strip()
    if not sub_id:
        return None

    return ClientRecord(
        sub_id=sub_id,
        group_name=str(row.get("groupName") or row.get("group_name") or "").strip(),
        email=str(row.get("email") or "").strip(),
        enable=True,
    )


def fetch_panel_clients_sync(settings: Settings, repository: CatalogRepository) -> list[dict[str, Any]]:
    token = resolve_panel_token(settings, repository.get_setting("panel_api_token"))
    web_path = resolve_panel_web_base_path(
        settings,
        repository.get_setting(PANEL_WEB_BASE_PATH_KEY),
    )
    client = PanelApiClient(settings, token, web_base_path=web_path)
    return client.fetch_clients_list()


def sync_clients(settings: Settings, repository: CatalogRepository) -> dict[str, int]:
    try:
        clients_raw = fetch_panel_clients_sync(settings, repository)
    except PanelApiError as exc:
        raise ValueError(str(exc)) from exc

    clients: list[ClientRecord] = []
    for row in clients_raw:
        client = _client_from_panel_row(row)
        if client is not None:
            clients.append(client)

    upserted, removed = repository.upsert_clients(clients)
    groups = {client.group_name for client in clients if client.group_name}

    logger.info(
        "client sync complete: panel_clients=%s upserted=%s removed=%s groups=%s",
        len(clients_raw),
        upserted,
        removed,
        len(groups),
    )
    return {
        "panel_clients": len(clients_raw),
        "upserted": upserted,
        "removed": removed,
        "groups": len(groups),
    }