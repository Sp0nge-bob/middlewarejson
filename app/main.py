import logging

from fastapi import FastAPI

from app.config import settings
from app.db.database import Database
from app.db.repository import CatalogRepository
from app.routes.subscription import router
from app.services.factory import build_transform_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(title="middlewarejson", version="0.2.0")
app.state.settings = settings
app.state.transform_service = build_transform_service(settings)
app.include_router(router)


@app.on_event("startup")
def _log_transform_readiness() -> None:
    mode = settings.transform_mode.strip().lower()
    repo = CatalogRepository(Database(settings.db_path))
    balancer_count = len(repo.list_balancers())
    logger.info("TRANSFORM_MODE=%s, balancers in db=%s", settings.transform_mode, balancer_count)
    if balancer_count and mode != "rules":
        logger.warning(
            "Балансировщики в базе есть, но TRANSFORM_MODE=%s — "
            "в подписке они не применяются. Установите TRANSFORM_MODE=rules в .env",
            settings.transform_mode,
        )