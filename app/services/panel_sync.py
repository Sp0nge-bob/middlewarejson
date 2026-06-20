from __future__ import annotations

import asyncio
import logging
import re
import threading
from datetime import timedelta

from app.config import Settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.services.catalog_sync import sync_catalog
from app.services.client_sync import sync_clients
from app.services.panel_api import (
    PANEL_API_TOKEN_KEY,
    resolve_panel_token,
)

logger = logging.getLogger(__name__)

_SYNC_LOCK = threading.Lock()
_INTERVAL_PATTERN = re.compile(r"^(\d+)([hdm])$", re.IGNORECASE)
_MIN_SYNC_INTERVAL = timedelta(minutes=5)


def parse_sync_interval(value: str) -> timedelta | None:
    raw = value.strip().lower()
    if not raw:
        return None

    match = _INTERVAL_PATTERN.fullmatch(raw)
    if not match:
        raise ValueError(
            f"invalid sync interval '{value}', expected format like 30m, 12h, 24h, 7d"
        )

    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError(f"invalid sync interval '{value}', amount must be positive")

    unit = match.group(2).lower()
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def run_panel_sync(settings: Settings, *, reason: str) -> bool:
    """Синхронизировать каталог и клиентов. Возвращает True при успехе."""
    repository = CatalogRepository(Database(settings.db_path))
    token = resolve_panel_token(settings, repository.get_setting(PANEL_API_TOKEN_KEY))
    if not token:
        logger.warning(
            "panel sync skipped (%s): Panel API token is not configured",
            reason,
        )
        return False

    with _SYNC_LOCK:
        try:
            catalog_result = sync_catalog(settings, repository)
            clients_result = sync_clients(settings, repository)
        except Exception as exc:
            logger.error("panel sync failed (%s): %s", reason, exc)
            return False

    logger.info(
        "panel sync ok (%s): catalog_active=%s catalog_upserted=%s "
        "clients=%s groups=%s groups_with_clients=%s removed=%s",
        reason,
        catalog_result["total_active"],
        catalog_result["upserted"],
        clients_result["upserted"],
        clients_result["groups"],
        clients_result["groups_with_clients"],
        clients_result["removed"],
    )
    return True


async def run_panel_sync_async(settings: Settings, *, reason: str) -> bool:
    return await asyncio.to_thread(run_panel_sync, settings, reason=reason)


async def panel_sync_scheduler(settings: Settings) -> None:
    try:
        interval = parse_sync_interval(settings.panel_sync_interval)
    except ValueError as exc:
        logger.error("panel sync scheduler disabled: %s", exc)
        return

    if interval is None:
        return
    if interval < _MIN_SYNC_INTERVAL:
        logger.error(
            "panel sync scheduler disabled: interval %s is below minimum %s",
            settings.panel_sync_interval.strip(),
            _MIN_SYNC_INTERVAL,
        )
        return

    logger.info(
        "panel sync scheduler started: every %s (%.0f sec)",
        settings.panel_sync_interval.strip(),
        interval.total_seconds(),
    )

    while True:
        await asyncio.sleep(interval.total_seconds())
        await run_panel_sync_async(settings, reason="schedule")