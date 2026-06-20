import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.routes.subscription import router
from app.services.factory import build_transform_service
from app.services.panel_api import PANEL_API_BASE_URL_KEY, resolve_upstream_base_url
from app.services.panel_sync import panel_sync_scheduler, run_panel_sync_async

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def _log_transform_readiness() -> None:
    mode = settings.transform_mode.strip().lower()
    repo = CatalogRepository(Database(settings.db_path))
    balancer_count = len(repo.list_balancers())
    upstream_base = resolve_upstream_base_url(
        settings,
        repo.get_setting(PANEL_API_BASE_URL_KEY),
    )
    upstream_path = settings.upstream_json_path.rstrip("/")
    logger.info("TRANSFORM_MODE=%s, balancers in db=%s", settings.transform_mode, balancer_count)
    logger.info("upstream target: %s%s/<sub_id>", upstream_base, upstream_path)
    if balancer_count and mode != "rules":
        logger.warning(
            "Балансировщики в базе есть, но TRANSFORM_MODE=%s — "
            "в подписке они не применяются. Установите TRANSFORM_MODE=rules в .env",
            settings.transform_mode,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_transform_readiness()

    if settings.panel_sync_on_startup:
        await run_panel_sync_async(settings, reason="startup")

    scheduler_task: asyncio.Task[None] | None = None
    if settings.panel_sync_interval.strip():
        scheduler_task = asyncio.create_task(panel_sync_scheduler(settings))

    yield

    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="middlewarejson", version="0.2.0", lifespan=lifespan)
app.state.settings = settings
app.state.transform_service = build_transform_service(settings)
app.include_router(router)