import logging
from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

PANEL_API_TOKEN_KEY = "panel_api_token"
PANEL_WEB_BASE_PATH_KEY = "panel_web_base_path"


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


class PanelApiError(Exception):
    pass


class PanelApiClient:
    def __init__(
        self,
        settings: Settings,
        token: str,
        *,
        web_base_path: str | None = None,
    ) -> None:
        self._settings = settings
        self._token = token.strip()
        self._web_path = (web_base_path or settings.panel_web_base_path).strip("/")
        if not self._token:
            raise PanelApiError(
                "Panel API token is not set. "
                "Set PANEL_API_TOKEN in .env or: python -m app.cli settings set --panel-token <token>"
            )

    def _base_url(self) -> str:
        base = self._settings.resolved_panel_base_url()
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
        if not isinstance(obj, list):
            raise PanelApiError("clients/groups obj is not a list")
        return [item for item in obj if isinstance(item, dict)]

    def test_connection(self) -> int:
        inbounds = self.fetch_inbounds_list()
        logger.info("panel api ok: %s inbounds", len(inbounds))
        return len(inbounds)