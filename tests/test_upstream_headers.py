from app.services.upstream import JSON_CLIENT_USER_AGENT, PASSTHROUGH_RESPONSE_HEADERS, _headers_for_upstream


def test_replaces_httpx_user_agent() -> None:
    headers = _headers_for_upstream({"User-Agent": "python-httpx/0.28.0", "Accept": "*/*"})
    assert headers["User-Agent"] == JSON_CLIENT_USER_AGENT
    assert headers["Accept"] == "application/json"


def test_keeps_happ_user_agent() -> None:
    headers = _headers_for_upstream({"User-Agent": "Happ/2.1.0"})
    assert headers["User-Agent"] == "Happ/2.1.0"


def test_forwards_hwid_but_not_request_credentials() -> None:
    headers = _headers_for_upstream({
        "User-Agent": "Happ/6.0.0", "X-HWID": "dummy", "X-Device-OS": "iOS",
        "X-Ver-OS": "18.0", "X-Device-Model": "iPhone", "Authorization": "private",
        "Cookie": "private", "Host": "untrusted.invalid",
    })
    assert headers["X-HWID"] == "dummy"
    assert headers["X-Device-OS"] == "iOS"
    assert headers["X-Ver-OS"] == "18.0"
    assert headers["X-Device-Model"] == "iPhone"
    assert not {"Authorization", "Cookie", "Host"} & headers.keys()
    assert {"providerid", "hide-settings", "dns-from-json-enable", "fallback-url", "new-url",
            "x-hwid-max-devices-reached"} <= set(PASSTHROUGH_RESPONSE_HEADERS)
