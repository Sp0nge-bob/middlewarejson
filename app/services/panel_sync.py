from __future__ import annotations

import asyncio
import logging
import re
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_sync_time(value: str) -> tuple[int, int] | None:
    raw = value.strip()
    if not raw:
        return None
    match = _TIME_PATTERN.match(raw)
    if not match:
        raise ValueError(f"invalid sync time '{value}', expected HH:MM")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"invalid sync time '{value}', expected HH:MM")
    return hour, minute


def resolve_sync_timezone(name: str) -> ZoneInfo:
    raw = name.strip()
    if not raw:
        return ZoneInfo("localtime")
    return ZoneInfo(raw)


def next_sync_at(
    now: datetime,
    hour: int,
    minute: int,
) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


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
        "clients=%s groups=%s removed=%s",
        reason,
        catalog_result["total_active"],
        catalog_result["upserted"],
        clients_result["upserted"],
        clients_result["groups"],
        clients_result["removed"],
    )
    return True


async def run_panel_sync_async(settings: Settings, *, reason: str) -> bool:
    return await asyncio.to_thread(run_panel_sync, settings, reason=reason)


async def panel_sync_scheduler(settings: Settings) -> None:
    parsed = parse_sync_time(settings.panel_sync_at)
    if parsed is None:
        return
    hour, minute = parsed

    try:
        tz = resolve_sync_timezone(settings.panel_sync_timezone)
    except Exception as exc:
        logger.error("panel sync scheduler disabled: invalid timezone: %s", exc)
        return

    logger.info(
        "panel sync scheduler started: daily at %02d:%02d (%s)",
        hour,
        minute,
        tz.key if hasattr(tz, "key") else settings.panel_sync_timezone or "localtime",
    )

    while True:
        now = datetime.now(tz)
        target = next_sync_at(now, hour, minute)
        delay_sec = max(1.0, (target - now).total_seconds())
        logger.info(
            "panel sync next run at %s (in %.0f sec)",
            target.isoformat(timespec="minutes"),
            delay_sec,
        )
        await asyncio.sleep(delay_sec)
        await run_panel_sync_async(settings, reason="schedule")