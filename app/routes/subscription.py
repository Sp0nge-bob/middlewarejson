import json
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.models.subscription import (
    SubscriptionPayload,
    try_load_json_subscription,
    validate_sub_id,
)
from app.services.upstream import UpstreamClient, UpstreamError

logger = logging.getLogger(__name__)


def _serialize_payload(payload: SubscriptionPayload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _headers_without_content_type(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() != "content-type"}


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
        upstream = UpstreamClient(settings, base_url=settings.resolved_upstream_base_url())
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

        try:
            payload = try_load_json_subscription(result.body)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            snippet = result.body.strip().replace("\n", " ")[:180]
            logger.warning(
                "invalid upstream json for sub_id=%s: %s; body=%s",
                sub_id,
                exc,
                snippet or "(empty)",
            )
            return PlainTextResponse(status_code=502, content="invalid upstream json")

        if payload is None:
            headers = {
                **_headers_without_content_type(result.headers),
                "Cache-Control": "no-store",
            }
            content_type = next(
                (value for key, value in result.headers.items() if key.lower() == "content-type"),
                "text/plain; charset=utf-8",
            )
            headers["Content-Type"] = content_type
            if request.method == "HEAD":
                return Response(status_code=200, headers=headers)
            return PlainTextResponse(status_code=200, content=result.body, headers=headers)

        try:
            transformed = request.app.state.transform_service.transform(sub_id, payload)
            body = _serialize_payload(transformed)
        except Exception as exc:
            logger.exception("transform failed for sub_id=%s: %s", sub_id, exc)
            return PlainTextResponse(status_code=500, content="transform failed")

        headers = {
            **_headers_without_content_type(result.headers),
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        }
        if request.method == "HEAD":
            return Response(status_code=200, headers=headers)
        return PlainTextResponse(status_code=200, content=body, headers=headers)

    @router.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return router