"""Offline per-application admission, pool isolation and structural budgets."""
import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.main import app
from app.models.subscription import try_load_json_subscription

CLIENT = httpx.AsyncClient


def test_mid002_json_depth_rejected_before_decoder():
    body = '{"outbounds":[],"nested":' + "[" * 80 + "0" + "]" * 80 + "}"
    with patch("app.models.subscription.json.loads", side_effect=AssertionError("decoder must not run")):
        with pytest.raises(ValueError, match="depth"):
            try_load_json_subscription(body)


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_mid002_busy_application_rejects_without_waiting(monkeypatch, method):
    settings = Settings(_env_file=None, upstream_base_url="https://upstream.invalid", max_inflight_subscriptions=1)
    monkeypatch.setattr(app.state, "settings", settings)
    monkeypatch.setattr("app.main._log_transform_readiness", lambda: None)

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        upstream_calls = []
        async def handle(request):
            upstream_calls.append(request)
            entered.set()
            await release.wait()
            return httpx.Response(200, stream=httpx.ByteStream(b"synthetic-base64"))
        def factory(**kwargs):
            return CLIENT(transport=httpx.MockTransport(handle), **kwargs)
        browser = CLIENT(transport=httpx.ASGITransport(app), base_url="http://testserver")
        with patch("httpx.AsyncClient", side_effect=factory):
            async with app.router.lifespan_context(app), browser:
                first = asyncio.create_task(browser.get("/json/syntheticToken1234"))
                await asyncio.wait_for(entered.wait(), 1)
                try:
                    second = await asyncio.wait_for(browser.request(method, "/json/syntheticToken5678"), .2)
                    assert second.status_code == 503
                    assert second.headers["retry-after"] == "1"
                    assert len(upstream_calls) == 1
                finally:
                    release.set()
                    await first
                assert (await browser.get("/json/syntheticToken5678")).status_code == 200
    asyncio.run(scenario())


def test_mid002_shared_pool_reuses_client_and_does_not_relay_cookies(monkeypatch):
    monkeypatch.setattr(app.state, "settings", Settings(_env_file=None, upstream_base_url="https://upstream.invalid"))
    monkeypatch.setattr("app.main._log_transform_readiness", lambda: None)
    created = []
    requests = []
    async def handle(request):
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"synthetic-base64"), headers={"set-cookie": "private=synthetic; Path=/"})
    def factory(**kwargs):
        client = CLIENT(transport=httpx.MockTransport(handle), **kwargs)
        created.append(client)
        return client
    async def scenario():
        browser = CLIENT(transport=httpx.ASGITransport(app), base_url="http://testserver")
        with patch("httpx.AsyncClient", side_effect=factory):
            async with app.router.lifespan_context(app), browser:
                assert (await browser.get("/json/syntheticToken1234")).status_code == 200
                assert (await browser.get("/json/syntheticToken5678")).status_code == 200
                assert len(created) == 1
                assert not created[0].is_closed
                assert not list(created[0].cookies.jar)
        assert created[0].is_closed
        assert all("cookie" not in request.headers for request in requests)
    asyncio.run(scenario())


@pytest.mark.parametrize("depth", [1, 8, 64, 128])
def test_mid002_depth_boundary_is_inclusive(depth):
    # The outer object counts as depth 1; outbounds itself requires depth 2.
    if depth == 1:
        with pytest.raises(ValueError, match="depth"):
            try_load_json_subscription('{"outbounds":[]}', max_depth=1)
        return
    body = '{"outbounds":[],"meta":' + "[" * (depth - 1) + "0" + "]" * (depth - 1) + "}"
    assert try_load_json_subscription(body, max_depth=depth) == json.loads(body)
    with pytest.raises(ValueError, match="depth"):
        try_load_json_subscription(body, max_depth=depth - 1)


@pytest.mark.parametrize("text", ['[' * 1000 + ']' * 1000, 'braces{}[] and quote" slash\\',
    '\\"' * 100 + '[{\\', '\\u0022' * 100])
def test_mid002_depth_ignores_strings_and_escape_sequences(text):
    payload = {"outbounds": [], "metadata": text}
    assert try_load_json_subscription(json.dumps(payload), max_depth=2) == payload


def test_mid002_extreme_depth_stops_before_python_recursion():
    body = '{"outbounds":[],"meta":' + "[" * 5000 + "0" + "]" * 5000 + "}"
    with pytest.raises(ValueError, match="depth"):
        try_load_json_subscription(body)


def test_mid002_budget_settings_defaults_aliases_and_validation(monkeypatch):
    defaults = Settings(_env_file=None)
    assert defaults.max_inflight_subscriptions == 8
    assert defaults.max_json_depth == 64
    monkeypatch.setenv("MAX_INFLIGHT_SUBSCRIPTIONS", "3")
    monkeypatch.setenv("MAX_JSON_DEPTH", "48")
    configured = Settings(_env_file=None)
    assert configured.max_inflight_subscriptions == 3
    assert configured.max_json_depth == 48
    for kwargs in ({"max_inflight_subscriptions": 0}, {"max_json_depth": 0}, {"max_json_depth": 129}):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **kwargs)


def test_mid002_cancelled_request_releases_admission_and_keeps_shared_pool(monkeypatch):
    monkeypatch.setattr(app.state, "settings", Settings(_env_file=None, upstream_base_url="https://upstream.invalid", max_inflight_subscriptions=1))
    monkeypatch.setattr("app.main._log_transform_readiness", lambda: None)
    async def scenario():
        entered = asyncio.Event()
        closed = asyncio.Event()
        call_count = 0
        class BlockedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial"
                entered.set()
                await asyncio.Event().wait()
            async def aclose(self):
                closed.set()
        async def handle(request):
            nonlocal call_count
            call_count += 1
            stream = BlockedStream() if call_count == 1 else httpx.ByteStream(b"synthetic-base64")
            return httpx.Response(200, stream=stream)
        client = CLIENT(transport=httpx.MockTransport(handle))
        browser = CLIENT(transport=httpx.ASGITransport(app), base_url="http://testserver")
        with patch("httpx.AsyncClient", return_value=client):
            async with app.router.lifespan_context(app), browser:
                pending = asyncio.create_task(browser.get("/json/syntheticToken1234"))
                await asyncio.wait_for(entered.wait(), 1)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
                assert closed.is_set()
                assert not client.is_closed
                assert (await browser.get("/json/syntheticToken5678")).status_code == 200
        assert client.is_closed
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["network", "invalid_json", "deep_json", "transform"])
def test_mid002_failed_request_releases_capacity(monkeypatch, failure):
    monkeypatch.setattr(app.state, "settings", Settings(_env_file=None, upstream_base_url="https://upstream.invalid", max_inflight_subscriptions=1))
    monkeypatch.setattr("app.main._log_transform_readiness", lambda: None)
    if failure == "transform":
        def broken(*args):
            raise ValueError("synthetic error")
        monkeypatch.setattr(app.state.transform_service, "transform", broken)
    async def handle(request):
        if failure == "network":
            raise httpx.ConnectError("synthetic error")
        body = {"invalid_json": b"{invalid", "deep_json": b'{"outbounds":[],"x":' + b"[" * 80 + b"0" + b"]" * 80 + b"}",
                "transform": b'{"outbounds":[]}'}[failure]
        return httpx.Response(200, stream=httpx.ByteStream(body))
    async def scenario():
        pool = CLIENT(transport=httpx.MockTransport(handle))
        browser = CLIENT(transport=httpx.ASGITransport(app), base_url="http://testserver")
        with patch("httpx.AsyncClient", return_value=pool):
            async with app.router.lifespan_context(app), browser:
                for _ in range(2):
                    result = await browser.get("/json/syntheticToken1234")
                    assert result.status_code == (500 if failure == "transform" else 502)
                    assert not pool.is_closed
        assert pool.is_closed
    asyncio.run(scenario())


def test_mid002_no_lifespan_owns_and_closes_ephemeral_clients(monkeypatch):
    monkeypatch.setattr(app.state, "settings", Settings(_env_file=None, upstream_base_url="https://upstream.invalid"))
    created = []
    async def handle(request):
        return httpx.Response(200, stream=httpx.ByteStream(b"synthetic-base64"))
    def factory(**kwargs):
        pool = CLIENT(transport=httpx.MockTransport(handle), **kwargs)
        created.append(pool)
        return pool
    async def scenario():
        browser = CLIENT(transport=httpx.ASGITransport(app), base_url="http://testserver")
        with patch("httpx.AsyncClient", side_effect=factory):
            async with browser:  # deliberately no lifespan context
                for _ in range(2):
                    assert (await browser.get("/json/syntheticToken1234")).status_code == 200
                    assert created[-1].is_closed
        assert len(created) == 2
        assert app.state.upstream_runtime.client is None
    asyncio.run(scenario())


@pytest.mark.parametrize("finish", ["complete", "cancel", "send_error"])
def test_mid002_admission_covers_blocked_response_send(monkeypatch, finish):
    monkeypatch.setattr(app.state, "settings", Settings(_env_file=None, upstream_base_url="https://upstream.invalid", max_inflight_subscriptions=1))
    monkeypatch.setattr("app.main._log_transform_readiness", lambda: None)
    async def scenario():
        blocked = asyncio.Event()
        release = asyncio.Event()
        calls = 0
        async def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=httpx.ByteStream(b"a" * 65536))
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            if message["type"] == "http.response.body":
                blocked.set()
                await release.wait()
                if finish == "send_error":
                    raise OSError("synthetic disconnected consumer")
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "scheme": "http", "path": "/json/syntheticToken1234", "raw_path": b"/json/syntheticToken1234",
            "query_string": b"", "root_path": "", "headers": [], "server": ("testserver", 80), "client": ("127.0.0.1", 12345)}
        pool = CLIENT(transport=httpx.MockTransport(handle))
        browser = CLIENT(transport=httpx.ASGITransport(app), base_url="http://testserver")
        with patch("httpx.AsyncClient", return_value=pool):
            async with app.router.lifespan_context(app), browser:
                pending = asyncio.create_task(app(scope, receive, send))
                await asyncio.wait_for(blocked.wait(), 1)
                try:
                    response = await browser.head("/json/syntheticToken5678")
                    assert response.status_code == 503
                    assert calls == 1
                finally:
                    if finish == "cancel":
                        pending.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await pending
                    else:
                        release.set()
                        if finish == "send_error":
                            with pytest.raises(OSError):
                                await pending
                        else:
                            await pending
                assert (await browser.get("/json/syntheticToken5678")).status_code == 200
    asyncio.run(scenario())
