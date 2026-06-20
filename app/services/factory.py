from app.config import Settings
from app.services.transform_service import TransformService


def build_transform_service(settings: Settings) -> TransformService:
    return TransformService(settings)