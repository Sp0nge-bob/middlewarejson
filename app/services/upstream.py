import logging
from dataclasses import dataclass

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

PASSTHROUGH_REQUEST_HEADERS = ("user-agent", "accept", "accept-language")
JSON_CLIENT_USER_AGENT = "Happ/1.0"
_TOOL_USER_AGENTS = ("python-httpx", "python-requests", "aiohttp")
PASSTHROUGH_RESPONSE_HEADERS = (
    "content-type",
    "subscription-userinfo",
    "profile-update-interval",
    "profile-title",
    "support-url",
    "profile-web-page-url",
    "announce",
    "routing-enable",
    "routing",
)


@dataclass
class UpstreamResult:
    status_code: int
    body: str
    headers: dict[str, str]


class UpstreamError(Exception):
    pass


def _headers_for_upstream(request_headers: dict[str, str] | None) -> dict[str, str]:
    """3x-ui JSON path can switch format by User-Agent; keep Happ/curl, drop httpx."""
    headers: dict[str, str] = {"Accept": "application/json"}
    incoming_ua = ""
    for key, value in (request_headers or {}).items():
        lowered = key.lower()
        if lowered not in PASSTHROUGH_REQUEST_HEADERS:
            continue
        if lowered == "user-agent":
            incoming_ua = value
            continue
        if lowered == "accept":
            continue
        headers[key] = value
    ua_l = incoming_ua.lower()
    if incoming_ua and not any(marker in ua_l for marker in _TOOL_USER_AGENTS):
        headers["User-Agent"] = incoming_ua
    else:
        headers["User-Agent"] = JSON_CLIENT_USER_AGENT
    return headers


class UpstreamClient:
    def __init__(self, settings: Settings, *, base_url: str | None = None) -> None:
        self._settings = settings
        self._base_url = (base_url or settings.upstream_base_url).rstrip("/")

    def build_url(self, sub_id: str) -> str:
        path = self._settings.upstream_json_path.rstrip("/")
        return f"{self._base_url}{path}/{sub_id}"

    async def fetch(
        self,
        sub_id: str,
        *,
        query_string: str = "",
        request_headers: dict[str, str] | None = None,
    ) -> UpstreamResult:
        url = self.build_url(sub_id)
        if query_string:
            url = f"{url}?{query_string}"

        headers = _headers_for_upstream(request_headers)
        if self._settings.upstream_host_header:
            headers["Host"] = self._settings.upstream_host_header

        try:
            async with httpx.AsyncClient(
                timeout=self._settings.request_timeout_sec,
                verify=self._settings.upstream_verify_ssl,
            ) as client:
                response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("upstream timeout for sub_id=%s url=%s: %s", sub_id, url, exc)
            raise UpstreamError("upstream timeout") from exc
        except httpx.RequestError as exc:
            logger.warning(
                "upstream request error for sub_id=%s url=%s: %s",
                sub_id,
                url,
                exc,
            )
            raise UpstreamError("upstream unavailable") from exc

        passthrough_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() in PASSTHROUGH_RESPONSE_HEADERS
        }

        return UpstreamResult(
            status_code=response.status_code,
            body=response.text,
            headers=passthrough_headers,
        )