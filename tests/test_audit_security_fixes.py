"""Security regression cases using synthetic subscriptions and mock upstream only."""
import json
import logging
from unittest.mock import patch
from upstream_fixture import mock_upstream

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.subscription import try_load_json_subscription

TOKEN = "syntheticSubscriptionToken_123456"
SECRET = "synthetic-vless-private-value"
QUERY = "device=synthetic-private-query"


def mock_client(body, *, error=None):
    return mock_upstream(httpx.Response(200, text=body), error=error)


@pytest.mark.parametrize("body,status", [
    (json.dumps({"outbounds": [{"protocol": "vless", "settings": {"id": SECRET}}]}), 200),
    ('{"outbounds":"invalid","id":"' + SECRET + '"}', 502),
    ('{"outbounds":[' + SECRET, 502),
])
def test_mid001_response_logs_do_not_disclose_subscription(caplog, body, status):
    with caplog.at_level(logging.INFO), patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client(body)):
        response = TestClient(app).get("/json/" + TOKEN + "?" + QUERY)
    assert response.status_code == status
    for private in (TOKEN, SECRET, QUERY):
        assert private not in caplog.text


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
def test_mid001_request_error_logs_do_not_disclose_url(caplog, error_type):
    error = error_type("https://upstream.invalid/json/" + TOKEN + "?" + QUERY)
    with caplog.at_level(logging.INFO), patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client("", error=error)):
        response = TestClient(app).get("/json/" + TOKEN + "?" + QUERY)
    assert response.status_code == 502
    assert TOKEN not in caplog.text
    assert QUERY not in caplog.text


def test_mid001_transform_exception_does_not_disclose_payload(caplog, monkeypatch):
    def broken(*args):
        raise ValueError(SECRET)
    monkeypatch.setattr(app.state.transform_service, "transform", broken)
    with caplog.at_level(logging.INFO), patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client('{"outbounds":[]}')):
        response = TestClient(app).get("/json/" + TOKEN)
    assert response.status_code == 500
    assert SECRET not in caplog.text
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("payload", [{"outbounds": []}, [{"outbounds": []}]])
@pytest.mark.parametrize("prefix", ["\ufeff", "\ufeff \n\t"])
def test_mid003_bom_json_loads(payload, prefix):
    assert try_load_json_subscription(prefix + json.dumps(payload)) == payload


@pytest.mark.parametrize("body", ["\ufeff", "\ufeff \t\n", "\ufeff{broken", "\ufeff[]"])
def test_mid003_invalid_bom_payloads_stay_rejected(body):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        try_load_json_subscription(body)


def test_mid003_base64_is_untouched():
    assert try_load_json_subscription("dmxlc3M6Ly9zeW50aGV0aWM=") is None


@pytest.mark.parametrize("logger_name", ["httpx", "httpcore.http11", "httpcore.connection", "uvicorn.access"])
def test_mid001_transport_log_records_strip_args_and_tracebacks(caplog, logger_name):
    from app.safe_logging import configure_safe_transport_logging
    configure_safe_transport_logging()
    with caplog.at_level(logging.INFO):
        try:
            raise ValueError(SECRET)
        except ValueError:
            logging.getLogger(logger_name).exception("request %s %s", TOKEN, QUERY)
    assert TOKEN not in caplog.text
    assert QUERY not in caplog.text
    assert SECRET not in caplog.text


def test_mid001_correlation_is_stable_within_process_and_distinct():
    from app.safe_logging import subscription_log_id
    first = subscription_log_id(TOKEN)
    assert first == subscription_log_id(TOKEN)
    assert first != subscription_log_id(TOKEN + "different")
    assert len(first) == 16
    assert TOKEN not in first


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_mid003_bom_json_subscription_http(method):
    with patch("app.services.upstream.httpx.AsyncClient", return_value=mock_client('\ufeff {"outbounds":[]}')):
        response = TestClient(app).request(method, "/json/" + TOKEN)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    if method == "HEAD":
        assert response.content == b""
    else:
        assert response.json() == {"outbounds": []}
