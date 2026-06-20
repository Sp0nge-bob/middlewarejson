import logging
from typing import Any

from app.config import Settings
from app.db.repository import CatalogRepository, ClientRecord
from app.services.panel_api import (
    PANEL_API_BASE_URL_KEY,
    PANEL_API_TOKEN_KEY,
    PANEL_WEB_BASE_PATH_KEY,
    PanelApiClient,
    PanelApiError,
    parse_group_members,
    parse_group_names,
    resolve_panel_base_url,
    resolve_panel_token,
    resolve_panel_web_base_path,
)

logger = logging.getLogger(__name__)


def _make_panel_client(settings: Settings, repository: CatalogRepository) -> PanelApiClient:
    token = resolve_panel_token(settings, repository.get_setting(PANEL_API_TOKEN_KEY))
    web_path = resolve_panel_web_base_path(
        settings,
        repository.get_setting(PANEL_WEB_BASE_PATH_KEY),
    )
    base_url = resolve_panel_base_url(
        settings,
        repository.get_setting(PANEL_API_BASE_URL_KEY),
    )
    return PanelApiClient(
        settings,
        token,
        web_base_path=web_path,
        api_base_url=base_url,
    )


def _build_email_lookup(clients: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for row in clients:
        email = str(row.get("email") or "").strip().lower()
        if email:
            lookup[email] = row
    return lookup


def _extract_email(member: dict[str, Any]) -> str:
    return str(member.get("email") or member.get("Email") or "").strip()


def _resolve_client_record(
    group_name: str,
    member: dict[str, Any],
    email_lookup: dict[str, dict[str, Any]],
    panel_client: PanelApiClient,
) -> ClientRecord | None:
    email = _extract_email(member)
    if not email:
        return None

    sub_id = str(member.get("subId") or member.get("sub_id") or "").strip()
    enable = member.get("enable") is not False

    if not sub_id:
        cached = email_lookup.get(email.lower())
        if cached is not None:
            sub_id = str(cached.get("subId") or cached.get("sub_id") or "").strip()
            enable = cached.get("enable") is not False

    if not sub_id:
        detail = panel_client.fetch_client_by_email(email)
        if detail is not None:
            sub_id = str(detail.get("subId") or detail.get("sub_id") or "").strip()
            enable = detail.get("enable") is not False

    if not sub_id or not enable:
        return None

    return ClientRecord(
        sub_id=sub_id,
        group_name=group_name,
        email=email,
        enable=True,
    )


def collect_clients_from_groups(panel_client: PanelApiClient) -> tuple[list[ClientRecord], int]:
    groups_raw = panel_client.fetch_groups()
    group_names = parse_group_names(groups_raw)
    email_lookup = _build_email_lookup(panel_client.fetch_clients_list())

    clients: list[ClientRecord] = []
    seen_sub_ids: set[str] = set()

    for group_name in group_names:
        members = panel_client.fetch_group_emails(group_name)
        for member in members:
            record = _resolve_client_record(group_name, member, email_lookup, panel_client)
            if record is None or record.sub_id in seen_sub_ids:
                continue
            seen_sub_ids.add(record.sub_id)
            clients.append(record)

    return clients, len(group_names)


def sync_clients(settings: Settings, repository: CatalogRepository) -> dict[str, int]:
    try:
        panel_client = _make_panel_client(settings, repository)
        clients, groups_count = collect_clients_from_groups(panel_client)
    except PanelApiError as exc:
        raise ValueError(str(exc)) from exc

    upserted, removed = repository.upsert_clients(clients)

    logger.info(
        "client sync complete: groups=%s clients=%s upserted=%s removed=%s",
        groups_count,
        len(clients),
        upserted,
        removed,
    )
    return {
        "groups": groups_count,
        "panel_clients": len(clients),
        "upserted": upserted,
        "removed": removed,
    }