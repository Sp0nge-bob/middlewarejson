"""Originally deferred findings; latest user decision authorizes these fixes."""
from unittest.mock import patch
from upstream_fixture import mock_upstream

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.transformers.ios_fix import apply_ios_fix_dns


def test_mid002_one_megabyte_subscription_remains_accepted_under_default_cap():
    body = "A" * (1024 * 1024)
    client = mock_upstream(httpx.Response(200, text=body))
    with patch("app.services.upstream.httpx.AsyncClient", return_value=client):
        response = TestClient(app).get("/json/syntheticToken1234")
    assert response.status_code == 200
    assert response.text == body


def test_mid004_conditional_dns_no_longer_suppresses_catch_all():
    conditional = {"type": "field", "port": 53, "domain": ["domain:example.invalid"], "outboundTag": "direct"}
    payload = {"outbounds": [{"tag": "direct", "protocol": "freedom"},
                              {"tag": "proxy", "protocol": "vless"}],
               "routing": {"rules": [conditional]}}
    result = apply_ios_fix_dns(payload)
    assert result["routing"]["rules"] == [conditional, {"type": "field", "port": 53,
        "network": "tcp,udp", "outboundTag": "proxy"}]
    assert payload["routing"]["rules"] == [conditional]
