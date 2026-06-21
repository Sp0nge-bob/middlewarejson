import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

PANEL_API_TOKEN_KEY = "panel_api_token"
PANEL_WEB_BASE_PATH_KEY = "panel_web_base_path"
PANEL_API_BASE_URL_KEY = "panel_api_base_url"
TRANSFORM_MODE_KEY = "transform_mode"

VALID_TRANSFORM_MODES = frozenset({"rules", "passthrough"})


def normalize_transform_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode not in VALID_TRANSFORM_MODES:
        raise ValueError(f"режим должен быть rules или passthrough, получено: {value!r}")
    return mode


def resolve_transform_mode(
    settings: Settings,
    repository_value: str | None,
) -> str:
    if repository_value and repository_value.strip():
        return normalize_transform_mode(repository_value)
    return normalize_transform_mode(settings.transform_mode)


def resolve_panel_token(settings: Settings, repository_token: str | None) -> str:
    if settings.panel_api_token:
        return settings.panel_api_token.strip()
    if repository_token:
        return repository_token.strip()
    return ""


def resolve_panel_web_base_path(
    settings: Settings,
    repository_value: str | None,
) -> str:
    if settings.panel_web_base_path:
        return settings.panel_web_base_path.strip()
    if repository_value:
        return repository_value.strip()
    return ""


def resolve_panel_base_url(
    settings: Settings,
    repository_value: str | None,
) -> str:
    if settings.panel_api_base_url:
        return settings.panel_api_base_url.strip().rstrip("/")
    if repository_value:
        return repository_value.strip().rstrip("/")
    return settings.upstream_base_url.rstrip("/")


def resolve_upstream_base_url(
    settings: Settings,
    repository_panel_url: str | None = None,
) -> str:
    explicit = settings.upstream_base_url.strip()
    if explicit:
        return explicit.rstrip("/")
    return resolve_panel_base_url(settings, repository_panel_url)


def parse_group_names(groups: list[Any]) -> list[str]:
    names: list[str] = []
    for item in groups:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(
                item.get("name")
                or item.get("groupName")
                or item.get("group_name")
                or ""
            ).strip()
        else:
            continue
        if name and name not in names:
            names.append(name)
    return names


def parse_group_members(obj: Any) -> list[dict[str, Any]]:
    if obj is None:
        return []
    if not isinstance(obj, list):
        return []

    members: list[dict[str, Any]] = []
    for item in obj:
        if isinstance(item, str):
            email = item.strip()
            if email:
                members.append({"email": email})
        elif isinstance(item, dict):
            members.append(item)
    return members


class PanelApiError(Exception):
    pass


@dataclass(frozen=True)
class PanelProbeResult:
    method: str
    url: str
    status_code: int | None
    elapsed_ms: float
    ok: bool
    summary: str
    inbound_count: int | None = None
    error: str | None = None


class PanelApiClient:
    def __init__(
        self,
        settings: Settings,
        token: str,
        *,
        web_base_path: str | None = None,
        api_base_url: str | None = None,
    ) -> None:
        self._settings = settings
        self._token = token.strip()
        self._web_path = (web_base_path or settings.panel_web_base_path).strip("/")
        self._api_base_url = (api_base_url or "").strip().rstrip("/")
        if not self._token:
            raise PanelApiError(
                "Panel API token is not set. "
                "Set PANEL_API_TOKEN in .env or: python -m app.cli settings set --panel-token <token>"
            )

    def _base_url(self) -> str:
        base = self._api_base_url or self._settings.resolved_panel_base_url()
        web_path = self._web_path
        if web_path:
            return f"{base}/{web_path}/"
        return f"{base}/"

    def _request(self, method: str, path: str) -> Any:
        url = urljoin(self._base_url(), path.lstrip("/"))
        headers = {"Authorization": f"Bearer {self._token}"}

        with httpx.Client(
            timeout=self._settings.request_timeout_sec,
            verify=self._settings.resolved_panel_verify_ssl(),
        ) as client:
            response = client.request(method, url, headers=headers)

        if response.status_code == 401:
            raise PanelApiError("Panel API authentication failed (401)")
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise PanelApiError(f"Unexpected Panel API response type: {type(payload)}")

        if payload.get("success") is False:
            message = payload.get("msg") or payload.get("message") or "unknown error"
            raise PanelApiError(f"Panel API error: {message}")

        return payload.get("obj")

    def fetch_inbounds_list(self) -> list[dict[str, Any]]:
        obj = self._request("GET", "/panel/api/inbounds/list")
        if obj is None:
            return []
        if not isinstance(obj, list):
            raise PanelApiError("inbounds/list obj is not a list")
        return [item for item in obj if isinstance(item, dict)]

    def fetch_clients_list(self) -> list[dict[str, Any]]:
        obj = self._request("GET", "/panel/api/clients/list")
        if obj is None:
            return []
        if not isinstance(obj, list):
            raise PanelApiError("clients/list obj is not a list")
        return [item for item in obj if isinstance(item, dict)]

    def fetch_groups(self) -> list[dict[str, Any]]:
        obj = self._request("GET", "/panel/api/clients/groups")
        if obj is None:
            return []
        if isinstance(obj, list):
            return [item for item in obj if isinstance(item, (dict, str))]
        raise PanelApiError("clients/groups obj is not a list")

    def fetch_group_emails(self, group_name: str) -> list[dict[str, Any]]:
        encoded = quote(group_name, safe="")
        obj = self._request("GET", f"/panel/api/clients/groups/{encoded}/emails")
        return parse_group_members(obj)

    def fetch_client_by_email(self, email: str) -> dict[str, Any] | None:
        encoded = quote(email, safe="")
        url = urljoin(self._base_url(), f"panel/api/clients/get/{encoded}")
        headers = {"Authorization": f"Bearer {self._token}"}

        with httpx.Client(
            timeout=self._settings.request_timeout_sec,
            verify=self._settings.resolved_panel_verify_ssl(),
        ) as client:
            response = client.get(url, headers=headers)

        if response.status_code in (401, 403):
            raise PanelApiError("Panel API authentication failed")
        if response.status_code == 404:
            return None
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise PanelApiError(f"Unexpected Panel API response type: {type(payload)}")
        if payload.get("success") is False:
            return None

        obj = payload.get("obj")
        return obj if isinstance(obj, dict) else None

    def probe_connection(self) -> PanelProbeResult:
        path = "/panel/api/inbounds/list"
        url = urljoin(self._base_url(), path.lstrip("/"))
        headers = {"Authorization": f"Bearer {self._token}"}
        started = time.perf_counter()

        try:
            with httpx.Client(
                timeout=self._settings.request_timeout_sec,
                verify=self._settings.resolved_panel_verify_ssl(),
            ) as client:
                response = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return PanelProbeResult(
                method="GET",
                url=url,
                status_code=None,
                elapsed_ms=elapsed_ms,
                ok=False,
                summary=f"ошибка сети: {exc}",
                error=str(exc),
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        status_code = response.status_code

        if status_code == 401:
            return PanelProbeResult(
                method="GET",
                url=url,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                ok=False,
                summary=f"HTTP {status_code} Unauthorized",
                error="Panel API authentication failed (401)",
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text.strip().replace("\n", " ")
            if len(body) > 160:
                body = body[:157] + "..."
            summary = f"HTTP {status_code}"
            if body:
                summary += f", body={body}"
            return PanelProbeResult(
                method="GET",
                url=url,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                ok=False,
                summary=summary,
                error=str(exc),
            )

        try:
            payload = response.json()
        except ValueError as exc:
            body = response.text.strip().replace("\n", " ")
            if len(body) > 160:
                body = body[:157] + "..."
            return PanelProbeResult(
                method="GET",
                url=url,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                ok=False,
                summary=f"HTTP {status_code}, не JSON: {body or '(пусто)'}",
                error=str(exc),
            )

        if not isinstance(payload, dict):
            return PanelProbeResult(
                method="GET",
                url=url,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                ok=False,
                summary=f"HTTP {status_code}, неожиданный тип ответа: {type(payload).__name__}",
                error=f"Unexpected Panel API response type: {type(payload)}",
            )

        if payload.get("success") is False:
            message = payload.get("msg") or payload.get("message") or "unknown error"
            return PanelProbeResult(
                method="GET",
                url=url,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                ok=False,
                summary=f"HTTP {status_code}, success=false, msg={message}",
                error=f"Panel API error: {message}",
            )

        obj = payload.get("obj")
        if obj is None:
            inbound_count = 0
            summary = f"HTTP {status_code}, success=true, obj=null"
        elif isinstance(obj, list):
            inbound_count = len(obj)
            summary = f"HTTP {status_code}, success=true, obj=[{inbound_count} элементов]"
        else:
            return PanelProbeResult(
                method="GET",
                url=url,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                ok=False,
                summary=f"HTTP {status_code}, success=true, obj={type(obj).__name__}",
                error="inbounds/list obj is not a list",
            )

        return PanelProbeResult(
            method="GET",
            url=url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            ok=True,
            summary=summary,
            inbound_count=inbound_count,
        )

    def test_connection(self) -> int:
        result = self.probe_connection()
        if not result.ok:
            raise PanelApiError(result.error or result.summary)
        logger.info("panel api ok: %s inbounds", result.inbound_count)
        return result.inbound_count or 0