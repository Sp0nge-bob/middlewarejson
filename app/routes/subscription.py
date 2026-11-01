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
from app.safe_logging import subscription_log_id
from app.services.upstream_runtime import UpstreamRuntime

logger = logging.getLogger(__name__)


def _serialize_payload(payload: SubscriptionPayload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _headers_without_content_type(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() != "content-type"}


class HeldResponse(Response):
    def __init__(self, inner: Response, release_fn) -> None:
        self.inner = inner
        self.release_fn = release_fn
        self.status_code = inner.status_code
        self.media_type = inner.media_type
        self.background = inner.background
        self.raw_headers = getattr(inner, "raw_headers", [])

    @property
    def headers(self):
        return self.inner.headers

    @property
    def body(self):
        return getattr(self.inner, "body", b"")

    async def __call__(self, scope, receive, send) -> None:
        try:
            await self.inner(scope, receive, send)
        finally:
            self.release_fn()


def build_subscription_router(json_path: str, *, runtime: UpstreamRuntime | None = None) -> APIRouter:
    router = APIRouter()
    runtime = runtime or UpstreamRuntime()
    route_path = f"{json_path.rstrip('/')}/{{sub_id}}"

    @router.api_route(
        route_path,
        methods=["GET", "HEAD"],
        response_class=PlainTextResponse,
    )
    async def get_subscription(sub_id: str, request: Request) -> Response:
        if not validate_sub_id(sub_id):
            return PlainTextResponse(status_code=400, content="invalid sub_id")

        lease = runtime.acquire(request.app.state.settings.max_inflight_subscriptions)
        if not lease.admitted:
            return PlainTextResponse(
                status_code=503,
                content="subscription service busy",
                headers={"Retry-After": "1", "Cache-Control": "no-store"},
            )

        try:
            response = await serve_subscription(sub_id, request)
            return HeldResponse(response, lease.release)
        except BaseException:
            lease.release()
            raise

    async def serve_subscription(sub_id: str, request: Request) -> Response:
        settings = request.app.state.settings
        upstream = UpstreamClient(settings, base_url=settings.resolved_upstream_base_url(), client=runtime.client)
        query_string = request.url.query

        try:
            result = await upstream.fetch(
                sub_id,
                query_string=query_string,
                request_headers=dict(request.headers),
            )
        except UpstreamError:
            return PlainTextResponse(status_code=502, content="upstream unavailable")

        error_headers = {
            **_headers_without_content_type(result.headers), "Cache-Control": "no-store",
        }
        if result.status_code == 404:
            return Response(status_code=404, headers=error_headers)
        if result.status_code >= 500:
            return PlainTextResponse(status_code=502, content="upstream error", headers=error_headers)
        if result.status_code != 200:
            return PlainTextResponse(status_code=result.status_code, content=result.body, headers=error_headers)

        try:
            payload = try_load_json_subscription(result.body, max_depth=settings.max_json_depth)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning(
                "invalid upstream json subscription=%s error_type=%s",
                subscription_log_id(sub_id),
                type(exc).__name__,
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
            logger.error("transform failed subscription=%s error_type=%s", subscription_log_id(sub_id), type(exc).__name__)
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
