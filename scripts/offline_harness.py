"""Isolation fixtures; HTTP transport mocks remain available, real sockets blocked."""
from pathlib import Path
import socket
import sys
import uuid
import pytest


@pytest.fixture
def tmp_path():
    target = Path(__file__).resolve().parents[1] / ".test_tmp" / ("case-" + uuid.uuid4().hex)
    target.mkdir(parents=True)
    return target


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    real_connect = socket.socket.connect
    def blocked(*args, **kwargs):
        # Windows builds asyncio's private wakeup socket using a loopback pair.
        caller = sys._getframe(1)
        if caller.f_code.co_name == "_fallback_socketpair" and caller.f_code.co_filename == socket.__file__:
            return real_connect(*args, **kwargs)
        raise AssertionError("Real network disabled in security regression tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
