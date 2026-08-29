from app.services.upstream import JSON_CLIENT_USER_AGENT, _headers_for_upstream


def test_replaces_httpx_user_agent() -> None:
    headers = _headers_for_upstream({"User-Agent": "python-httpx/0.28.0", "Accept": "*/*"})
    assert headers["User-Agent"] == JSON_CLIENT_USER_AGENT
    assert headers["Accept"] == "application/json"


def test_keeps_happ_user_agent() -> None:
    headers = _headers_for_upstream({"User-Agent": "Happ/2.1.0"})
    assert headers["User-Agent"] == "Happ/2.1.0"
