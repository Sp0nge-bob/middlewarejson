import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "sample_sub.json"
SAMPLE_BODY = FIXTURE.read_text(encoding="utf-8")
JSON_SUB_PATH = "/json"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _mock_upstream_response(
    *,
    status_code: int = 200,
    text: str = "",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(status_code, text=text, headers=headers or {})


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invalid_sub_id(client: TestClient) -> None:
    response = client.get(f"{JSON_SUB_PATH}/short")
    assert response.status_code == 400


def test_upstream_404(client: TestClient) -> None:
    mock_get = AsyncMock(return_value=_mock_upstream_response(status_code=404))
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client):
        response = client.get(f"{JSON_SUB_PATH}/abcd1234efgh5678")

    assert response.status_code == 404
    assert response.text == ""


def test_head_broken_json_is_502_not_200(client: TestClient) -> None:
    mock_get = AsyncMock(return_value=_mock_upstream_response(status_code=200, text="{not-json"))
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client):
        response = client.head(f"{JSON_SUB_PATH}/abcd1234efgh5678")

    assert response.status_code == 502


def test_base64_subscription_is_passed_through(client: TestClient) -> None:
    raw = "dmxlc3M6Ly8xMjM0NTY3OC1hYmNkLTEyMzQtYWJjZC0xMjM0NTY3ODlhYmNAZXhhbXBsZS5jb206NDQz"
    mock_get = AsyncMock(
        return_value=_mock_upstream_response(
            status_code=200,
            text=raw,
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Subscription-Userinfo": "upload=0; download=0; total=0; expire=0",
            },
        )
    )
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client):
        response = client.get(f"{JSON_SUB_PATH}/abcd1234efgh5678")

    assert response.status_code == 200
    assert response.text == raw
    assert response.headers["subscription-userinfo"] == (
        "upload=0; download=0; total=0; expire=0"
    )
    assert "application/json" not in response.headers["content-type"]


def test_head_base64_subscription_is_200(client: TestClient) -> None:
    mock_get = AsyncMock(
        return_value=_mock_upstream_response(
            status_code=200,
            text="dmxlc3M6Ly9leGFtcGxl",
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
    )
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client):
        response = client.head(f"{JSON_SUB_PATH}/abcd1234efgh5678")

    assert response.status_code == 200
    assert response.text == ""


def test_passthrough_json_and_headers(client: TestClient) -> None:
    mock_get = AsyncMock(
        return_value=_mock_upstream_response(
            status_code=200,
            text=SAMPLE_BODY,
            headers={
                "Subscription-Userinfo": "upload=0; download=0; total=0; expire=0",
                "Profile-Update-Interval": "10",
            },
        )
    )
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client):
        response = client.get(f"{JSON_SUB_PATH}/abcd1234efgh5678")

    assert response.status_code == 200
    assert response.headers["subscription-userinfo"] == (
        "upload=0; download=0; total=0; expire=0"
    )
    assert response.headers["profile-update-interval"] == "10"
    assert response.headers["content-type"].startswith("application/json")
    assert json.loads(response.text) == json.loads(SAMPLE_BODY)