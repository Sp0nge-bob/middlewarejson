import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.database import Database
from app.db.repository import SettingsRepository
from app.routes.subscription import build_subscription_router
from app.services.factory import build_transform_service
from app.services.mode import TRANSFORM_MODE_KEY, resolve_transform_mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def _log_transform_readiness() -> None:
    repo = SettingsRepository(Database(settings.db_path))
    mode = resolve_transform_mode(settings, repo.get_setting(TRANSFORM_MODE_KEY))
    upstream_base = settings.resolved_upstream_base_url()
    upstream_path = settings.upstream_json_path.rstrip("/")
    logger.info("TRANSFORM_MODE=%s", mode)
    logger.info("upstream target: %s%s/<sub_id>", upstream_base, upstream_path)
    if not upstream_base:
        logger.warning("UPSTREAM_BASE_URL пуст — задайте URL sub-сервера 3x-ui в .env")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_transform_readiness()
    yield


app = FastAPI(title="middlewarejson", version="0.3.0", lifespan=lifespan)
app.state.settings = settings
app.state.transform_service = build_transform_service(settings)
app.include_router(build_subscription_router(settings.resolved_agent_json_path()))
