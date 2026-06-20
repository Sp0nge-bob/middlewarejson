import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "sample_sub.json"
SAMPLE_BODY = FIXTURE.read_text(encoding="utf-8")


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
    response = client.get("/json/short")
    assert response.status_code == 400


def test_upstream_404(client: TestClient) -> None:
    mock_get = AsyncMock(return_value=_mock_upstream_response(status_code=404))
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client):
        response = client.get("/json/abcd1234efgh5678")

    assert response.status_code == 404
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
        response = client.get("/json/abcd1234efgh5678")

    assert response.status_code == 200
    assert response.headers["subscription-userinfo"] == (
        "upload=0; download=0; total=0; expire=0"
    )
    assert response.headers["profile-update-interval"] == "10"
    assert response.headers["content-type"].startswith("application/json")
    assert json.loads(response.text) == json.loads(SAMPLE_BODY)