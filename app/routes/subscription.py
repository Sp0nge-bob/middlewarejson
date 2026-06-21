import json
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.db.database import Database
from app.db.repository import CatalogRepository
from app.models.subscription import SubscriptionPayload, validate_payload, validate_sub_id
from app.services.panel_api import PANEL_API_BASE_URL_KEY, resolve_upstream_base_url
from app.services.upstream import UpstreamClient, UpstreamError
from app.transformers.happ_sanitize import sanitize_for_happ

logger = logging.getLogger(__name__)


def _serialize_payload(payload: SubscriptionPayload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def build_subscription_router(json_path: str) -> APIRouter:
    router = APIRouter()
    route_path = f"{json_path.rstrip('/')}/{{sub_id}}"

    @router.api_route(
        route_path,
        methods=["GET", "HEAD"],
        response_class=PlainTextResponse,
    )
    async def get_subscription(sub_id: str, request: Request) -> Response:
        if not validate_sub_id(sub_id):
            return PlainTextResponse(status_code=400, content="invalid sub_id")

        settings = request.app.state.settings
        repo = CatalogRepository(Database(settings.db_path))
        upstream_base = resolve_upstream_base_url(
            settings,
            repo.get_setting(PANEL_API_BASE_URL_KEY),
        )
        upstream = UpstreamClient(settings, base_url=upstream_base)
        query_string = request.url.query

        try:
            result = await upstream.fetch(
                sub_id,
                query_string=query_string,
                request_headers=dict(request.headers),
            )
        except UpstreamError:
            return PlainTextResponse(status_code=502, content="upstream unavailable")

        if result.status_code == 404:
            return Response(status_code=404)
        if result.status_code >= 500:
            return PlainTextResponse(status_code=502, content="upstream error")
        if result.status_code != 200:
            return PlainTextResponse(status_code=result.status_code, content=result.body)

        if request.method == "HEAD":
            return Response(status_code=200, headers=result.headers)

        try:
            payload: SubscriptionPayload = json.loads(result.body)
            validate_payload(payload)
            if settings.happ_sanitize:
                payload = sanitize_for_happ(payload)
            transformed = request.app.state.transform_service.transform(sub_id, payload)
            body = _serialize_payload(transformed)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("invalid upstream json for sub_id=%s: %s", sub_id, exc)
            return PlainTextResponse(status_code=502, content="invalid upstream json")

        return PlainTextResponse(
            status_code=200,
            content=body,
            headers={
                **result.headers,
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )

    @router.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return router