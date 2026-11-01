import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.database import Database
from app.db.repository import SettingsRepository
from app.routes.subscription import build_subscription_router
from app.services.factory import build_transform_service
from app.services.mode import TRANSFORM_MODE_KEY, resolve_transform_mode
from app.services.feature_settings import ALLOWLIST_BALANCER_KEY, resolve_allowlist_balancer
from app.safe_logging import configure_safe_transport_logging
from app.services.upstream_runtime import UpstreamRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
configure_safe_transport_logging()

logger = logging.getLogger(__name__)


def _log_transform_readiness() -> None:
    repo = SettingsRepository(Database(settings.db_path))
    mode = resolve_transform_mode(settings, repo.get_setting(TRANSFORM_MODE_KEY))
    upstream_base = settings.resolved_upstream_base_url()
    logger.info("TRANSFORM_MODE=%s", mode)
    logger.info("ALLOWLIST_BALANCER_ENABLED=%s", resolve_allowlist_balancer(
        settings, repo.get_setting(ALLOWLIST_BALANCER_KEY),
    ))
    logger.info("upstream configured: %s", bool(upstream_base))
    if not upstream_base:
        logger.warning("UPSTREAM_BASE_URL пуст — задайте URL sub-сервера 3x-ui в .env")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_transform_readiness()
    await app.state.upstream_runtime.start(app.state.settings)
    try:
        yield
    finally:
        await app.state.upstream_runtime.stop()


app = FastAPI(title="middlewarejson", version="1.1.0", lifespan=lifespan)
app.state.settings = settings
app.state.transform_service = build_transform_service(settings)
app.state.upstream_runtime = UpstreamRuntime()
app.include_router(build_subscription_router(settings.resolved_agent_json_path(), runtime=app.state.upstream_runtime))
