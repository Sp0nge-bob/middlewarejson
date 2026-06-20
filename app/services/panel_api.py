import logging
from typing import Any
from urllib.parse import quote, urljoin

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

    def test_connection(self) -> int:
        inbounds = self.fetch_inbounds_list()
        logger.info("panel api ok: %s inbounds", len(inbounds))
        return len(inbounds)