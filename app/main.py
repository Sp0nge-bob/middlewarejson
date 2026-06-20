import logging

from fastapi import FastAPI

from app.config import settings
from app.routes.subscription import router
from app.services.factory import build_transform_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="middlewarejson", version="0.2.0")
app.state.settings = settings
app.state.transform_service = build_transform_service(settings)
app.include_router(router)