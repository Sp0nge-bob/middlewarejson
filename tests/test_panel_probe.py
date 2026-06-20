from unittest.mock import MagicMock, patch

import httpx

from app.config import Settings
from app.services.panel_api import PanelApiClient


def _settings() -> Settings:
    return Settings(
        panel_api_base_url="https://127.0.0.1:9001",
        panel_web_base_path="/panel-path",
        panel_api_token="test-token",
    )


def test_probe_connection_success() -> None:
    response = httpx.Response(
        200,
        json={"success": True, "obj": [{"id": 1}, {"id": 2}]},
        request=httpx.Request("GET", "https://example.test/inbounds/list"),
    )
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = response

    with patch("app.services.panel_api.httpx.Client", return_value=mock_client):
        result = PanelApiClient(_settings(), "test-token").probe_connection()

    assert result.ok is True
    assert result.status_code == 200
    assert result.inbound_count == 2
    assert "2 элементов" in result.summary
    assert result.elapsed_ms >= 0
    assert result.url.endswith("/panel-path/panel/api/inbounds/list")


def test_probe_connection_auth_failure() -> None:
    response = httpx.Response(
        401,
        text="unauthorized",
        request=httpx.Request("GET", "https://example.test/inbounds/list"),
    )
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = response

    with patch("app.services.panel_api.httpx.Client", return_value=mock_client):
        result = PanelApiClient(_settings(), "bad-token").probe_connection()

    assert result.ok is False
    assert result.status_code == 401
    assert "401" in result.summary