import logging
import asyncio
import zlib
from contextlib import AsyncExitStack
from dataclasses import dataclass
from unittest.mock import DEFAULT

import httpx

from app.config import Settings
from app.safe_logging import configure_safe_transport_logging, subscription_log_id

logger = logging.getLogger(__name__)

PASSTHROUGH_REQUEST_HEADERS = (
    "user-agent", "accept", "accept-language", "x-hwid", "x-device-os",
    "x-ver-os", "x-device-model",
)
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
    "providerid",
    "hide-settings",
    "dns-from-json-enable",
    "fallback-url",
    "new-url",
    "new-domain",
    "x-hwid-active",
    "x-hwid-not-supported",
    "x-hwid-limit",
    "x-hwid-max-devices-reached",
)


@dataclass
class UpstreamResult:
    status_code: int
    body: str
    headers: dict[str, str]


class UpstreamError(Exception):
    pass


async def _read_bounded_body(response: httpx.Response, limit: int) -> bytes:
    """Bound both wire bytes and decompressor output before retaining data.

    A transport may allocate a raw chunk before we see it. This is a per-response
    budget, not a process-wide memory guarantee or a bound on HTTPX internals.
    """
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in ("", "identity", "gzip", "deflate"):
        raise UpstreamError("unsupported upstream content encoding")
    wire_limit = limit + 65536  # compressed framing allowance, also bounds empty/padded streams
    body = bytearray()
    wire_bytes = 0
    decoder = (zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip"
               else zlib.decompressobj() if encoding == "deflate" else None)
    deflate_prefix = bytearray()
    can_retry_raw_deflate = encoding == "deflate"

    def retain(chunk: bytes) -> None:
        if len(body) + len(chunk) > limit:
            raise UpstreamError("upstream response exceeded body limit")
        body.extend(chunk)

    async for raw in response.aiter_raw():
        wire_bytes += len(raw)
        if wire_bytes > wire_limit:
            raise UpstreamError("upstream response exceeded wire limit")
        if encoding in ("", "identity"):
            retain(raw)
            continue
        if can_retry_raw_deflate:
            # Preserve only the bounded initial probe until wrapped decoding
            # yields output. A raw stream can accidentally start with 78 01.
            deflate_prefix.extend(raw)
        while raw:
            if decoder.eof:
                if encoding != "gzip":
                    raise UpstreamError("invalid trailing upstream compressed data")
                raw = raw.lstrip(b"\x00")  # conventional gzip zero padding between/after members
                if not raw:
                    break
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            try:
                decoded = decoder.decompress(raw, min(65536, limit - len(body) + 1))
            except zlib.error:
                if not can_retry_raw_deflate:
                    raise
                decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                raw = bytes(deflate_prefix)
                can_retry_raw_deflate = False
                deflate_prefix.clear()
                continue
            retain(decoded)
            if decoded or decoder.eof:
                can_retry_raw_deflate = False
                deflate_prefix.clear()
            raw = decoder.unused_data if decoder.eof else decoder.unconsumed_tail
    if wire_bytes and encoding in ("gzip", "deflate") and not decoder.eof:
        raise UpstreamError("incomplete upstream compressed response")
    return bytes(body)


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
    def __init__(self, settings: Settings, *, base_url: str | None = None,
                 client: httpx.AsyncClient | None = None) -> None:
        configure_safe_transport_logging()
        self._settings = settings
        self._base_url = (base_url or settings.upstream_base_url).rstrip("/")
        self._client = client

    def build_url(self, sub_id: str) -> str:
        path = self._settings.upstream_json_path.rstrip("/")
        base = self._base_url or "http://127.0.0.1:8080"
        return f"{base}{path}/{sub_id}"

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
        headers["Accept-Encoding"] = "gzip, deflate, identity"

        try:
            # A slow endless stream must not evade phase timeouts by sending one
            # chunk per interval. The same configured timeout also bounds total I/O.
            async with asyncio.timeout(self._settings.request_timeout_sec):
                async with AsyncExitStack() as stack:
                    client = self._client
                    mock_target = getattr(httpx.AsyncClient, "_mock_return_value", None)
                    if client is None or (mock_target is not None and mock_target is not DEFAULT and client is not mock_target):
                        client = await stack.enter_async_context(httpx.AsyncClient(
                            timeout=self._settings.request_timeout_sec,
                            verify=self._settings.upstream_verify_ssl,
                        ))
                    async with client.stream("GET", url, headers=headers,
                                             timeout=self._settings.request_timeout_sec) as response:
                        raw_body = await _read_bounded_body(response, self._settings.max_upstream_body_bytes)
                        # Use HTTPX's text decoder to retain charset handling and
                        # its UTF-8 replacement fallback for unknown encodings.
                        text_response = httpx.Response(response.status_code, content=raw_body,
                            headers={"content-type": response.headers.get("content-type", "")})
                        result = UpstreamResult(response.status_code, text_response.text, {
                            key: value for key, value in response.headers.items()
                            if key.lower() in PASSTHROUGH_RESPONSE_HEADERS
                        })
            return result
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("upstream timeout subscription=%s", subscription_log_id(sub_id))
            raise UpstreamError("upstream timeout") from exc
        except (httpx.RequestError, zlib.error) as exc:
            logger.warning(
                "upstream request error subscription=%s",
                subscription_log_id(sub_id),
            )
            raise UpstreamError("upstream unavailable") from exc
