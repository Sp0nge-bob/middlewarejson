"""Application-owned connection pool and non-queuing subscription admission."""
from contextlib import contextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from threading import Lock

import httpx

from app.config import Settings


class _RejectCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


class AdmissionLease:
    def __init__(self, runtime: "UpstreamRuntime", admitted: bool) -> None:
        self._runtime = runtime
        self.admitted = admitted
        self._released = False

    def release(self) -> None:
        if self.admitted and not self._released:
            self._released = True
            with self._runtime._lock:
                self._runtime._active -= 1

    def __enter__(self) -> bool:
        return self.admitted

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class UpstreamRuntime:
    def __init__(self) -> None:
        self.client: httpx.AsyncClient | None = None
        self._active = 0
        self._lock = Lock()

    def acquire(self, limit: int) -> AdmissionLease:
        with self._lock:
            admitted = self._active < limit
            if admitted:
                self._active += 1
        return AdmissionLease(self, admitted)

    @contextmanager
    def admission(self, limit: int):
        lease = self.acquire(limit)
        try:
            yield lease.admitted
        finally:
            lease.release()

    async def start(self, settings: Settings) -> None:
        if self.client is not None:
            raise RuntimeError("upstream runtime already started")
        self.client = httpx.AsyncClient(
            timeout=settings.request_timeout_sec,
            verify=settings.upstream_verify_ssl,
            limits=httpx.Limits(max_connections=settings.max_inflight_subscriptions,
                                max_keepalive_connections=settings.max_inflight_subscriptions),
            # A shared pool must not turn upstream cookies into cross-user state.
            cookies=CookieJar(policy=_RejectCookies()),
        )

    async def stop(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            await client.aclose()
