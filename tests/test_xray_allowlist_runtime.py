"""Optional tests against an official Xray v26.9.9 binary; all traffic is local.

Set XRAY_TEST_BINARY to its path. This validates upstream core, not Happ's
closed iOS Network Extension. No public VPN nodes or probe sites are contacted.
"""

import json
import os
import socket
import socketserver
import struct
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app.features.allowlist_balancer import DESCRIPTION, compose_allowlist_balancer
from app.transformers.ios_fix import apply_ios_fix, apply_ios_fix_dns

FIXTURE = Path(__file__).parent / "fixtures" / "priority_pools_3xui.json"
PROBE_IP = "198.18.0.2"
TRAFFIC_IP = "198.18.0.1"


@pytest.fixture
def xray_binary():
    value = os.environ.get("XRAY_TEST_BINARY")
    if not value:
        pytest.skip("set XRAY_TEST_BINARY to official Xray v26.9.9")
    binary = Path(value).resolve()
    version = subprocess.run([str(binary), "version"], capture_output=True, text=True, timeout=10)
    assert version.returncode == 0
    assert "Xray 26.9.9 " in version.stdout
    return binary


@pytest.mark.parametrize("mode", ["passthrough", "ios-fix", "ios-fix-dns"])
def test_official_core_accepts_real_transport_profile(xray_binary, tmp_path, mode):
    config = compose_allowlist_balancer(json.loads(FIXTURE.read_text(encoding="utf-8")))[0]
    if mode == "ios-fix":
        config = apply_ios_fix(config)
    elif mode == "ios-fix-dns":
        config = apply_ios_fix_dns(config)
    config_path = tmp_path / "profile.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    result = subprocess.run(
        [str(xray_binary), "run", "-test", "-c", str(config_path)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Configuration OK" in result.stdout


def _read(sock, count):
    data = b""
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise EOFError("socket closed")
        data += part
    return data


def _address(sock, atyp):
    if atyp == 1:
        return socket.inet_ntoa(_read(sock, 4))
    if atyp == 3:
        return _read(sock, _read(sock, 1)[0]).decode()
    if atyp == 4:
        return socket.inet_ntop(socket.AF_INET6, _read(sock, 16))
    raise ValueError("unsupported address")


class _Node(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, name, delay, gate):
        self.name = name
        self.delay = delay
        self.alive = True
        self.gate = gate
        self.probes = 0
        self.user_attempts = 0
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.udp.settimeout(0.1)
        super().__init__(("127.0.0.1", 0), _SocksHandler)
        self.tcp_thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.udp_thread = threading.Thread(target=self._udp_loop, daemon=True)
        self.tcp_thread.start()
        self.udp_thread.start()

    def _udp_loop(self):
        while not self.stopped.is_set():
            try:
                data, peer = self.udp.recvfrom(65535)
                if len(data) < 10 or data[:4] != b"\0\0\0\x01":
                    continue
                with self.lock:
                    self.user_attempts += 1
                if self.alive:
                    self.udp.sendto(data[:10] + self.name.encode(), peer)
            except socket.timeout:
                pass
            except OSError:
                return

    def close(self):
        self.stopped.set()
        self.shutdown()
        self.server_close()
        self.udp.close()
        self.tcp_thread.join(timeout=2)
        self.udp_thread.join(timeout=2)


class _SocksHandler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.settimeout(8)
        node = self.server
        try:
            header = _read(sock, 2)
            _read(sock, header[1])
            sock.sendall(b"\x05\x00")
            header = _read(sock, 4)
            address = _address(sock, header[3])
            _read(sock, 2)  # target port
            if header[1] == 3:  # UDP ASSOCIATE
                sock.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", node.udp.getsockname()[1]))
                while sock.recv(1):
                    pass
                return
            is_probe = address == PROBE_IP
            if not is_probe:
                with node.lock:
                    node.user_attempts += 1
            if not node.alive:
                sock.sendall(b"\x05\x01\x00\x01" + b"\x00" * 6)
                if is_probe:
                    with node.lock:
                        node.probes += 1
                return
            sock.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
            data = b""
            while b"\r\n\r\n" not in data:
                data += _read(sock, 1)
            if is_probe:
                node.gate.wait(timeout=7)
                time.sleep(node.delay)
            body = node.name.encode()
            sock.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            if is_probe:
                with node.lock:
                    node.probes += 1
        except (OSError, EOFError, ValueError):
            pass


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _socks(inbound, port, command=1, address=TRAFFIC_IP):
    sock = socket.create_connection(("127.0.0.1", inbound), timeout=3)
    sock.settimeout(3)
    sock.sendall(b"\x05\x01\x00")
    assert _read(sock, 2) == b"\x05\x00"
    address = "0.0.0.0" if command == 3 else address
    sock.sendall(bytes([5, command, 0, 1]) + socket.inet_aton(address) + struct.pack("!H", port))
    header = _read(sock, 4)
    assert header[1] == 0
    address = _address(sock, header[3])
    bound_port = struct.unpack("!H", _read(sock, 2))[0]
    return sock, address, bound_port


def _request(inbound, port=80, address=TRAFFIC_IP):
    try:
        sock, _, _ = _socks(inbound, port, address=address)
        with sock:
            sock.sendall(f"GET /traffic HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n".encode())
            data = b""
            while True:
                part = sock.recv(4096)
                if not part:
                    break
                data += part
                if b"\r\n\r\n" in data:
                    headers, body = data.split(b"\r\n\r\n", 1)
                    lengths = [line.split(b":", 1)[1].strip() for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length:")]
                    if lengths and len(body) >= int(lengths[0]):
                        break
        return data.split(b"\r\n\r\n", 1)[1].decode() if b"\r\n\r\n" in data else None
    except (OSError, EOFError):
        return None


def _dns_udp(inbound):
    tcp, address, port = _socks(inbound, 0, command=3)
    with tcp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.settimeout(3)
        packet = b"\0\0\0\x01" + socket.inet_aton(TRAFFIC_IP) + struct.pack("!H", 53) + b"dns-query"
        udp.sendto(packet, ("127.0.0.1" if address == "0.0.0.0" else address, port))
        response = udp.recv(65535)
        assert response[:4] == b"\0\0\0\x01"
        return response[10:].decode()


def _round(nodes):
    before = [node.probes for node in nodes]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if all(node.probes > count for node, count in zip(nodes, before)):
            time.sleep(0.1)  # allow observer to publish the just-completed response
            return
        time.sleep(0.02)
    raise AssertionError("probe round did not finish")


def _expect(inbound, names):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        results = [_request(inbound) for _ in range(3)]
        if all(result in names for result in results):
            return
        time.sleep(0.05)
    raise AssertionError(f"expected {names}, received {results}")


class _DirectHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                data += _read(self.request, 1)
            self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nDIRECT")
        except (OSError, EOFError):
            pass


@pytest.mark.parametrize("fix", [lambda x: x, apply_ios_fix, apply_ios_fix_dns], ids=["passthrough", "ios-fix", "ios-fix-dns"])
def test_real_core_priority_latency_recovery_and_dns(xray_binary, tmp_path, fix):
    gate = threading.Event()
    nodes = [_Node(name, delay, gate) for name, delay in [
        ("A1", 0.3), ("A2", 0.3), ("A3", 2.0), ("B1", 0.05), ("B2", 0.15),
    ]]
    process = None
    direct = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _DirectHandler)
    direct.daemon_threads = True
    direct_thread = threading.Thread(target=direct.serve_forever, daemon=True)
    direct_thread.start()
    log_path = tmp_path / "xray.log"
    try:
        pools = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for pool in pools:
            pool["routing"]["rules"][:0] = [
                {"type": "field", "ip": ["127.0.0.1"], "outboundTag": "direct"},
                {"type": "field", "ip": ["192.0.2.1"], "outboundTag": "block"},
            ]
        for outbound, node in zip([o for p in pools for o in p["outbounds"] if o["protocol"] == "vless"], nodes):
            outbound["protocol"] = "socks"
            outbound["settings"] = {"servers": [{"address": "127.0.0.1", "port": node.server_address[1]}]}
            outbound.pop("streamSettings")
        config = fix(compose_allowlist_balancer(pools)[0])
        inbound = _port()
        config["inbounds"] = [config["inbounds"][0]]
        config["inbounds"][0]["port"] = inbound
        # Local-only HTTP probes are solely for this isolated test harness.
        config["observatory"]["probeUrl"] = f"http://{PROBE_IP}/probe"
        config["observatory"]["probeInterval"] = "0.1s"
        config["log"] = {"loglevel": "info"}
        path = tmp_path / "runtime.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(xray_binary), "run", "-c", str(path)], stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + 5
            while True:
                assert process.poll() is None, log_path.read_text(encoding="utf-8")
                try:
                    with socket.create_connection(("127.0.0.1", inbound), timeout=0.2):
                        break
                except OSError:
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
            # Empty observation report must not prematurely select B.
            assert all(_request(inbound) in {"A1", "A2", "A3"} for _ in range(6))
            assert nodes[3].user_attempts == nodes[4].user_attempts == 0
            gate.set()
            _round(nodes)
            _expect(inbound, {"A1", "A2"})  # A3=2000 ms; B is faster but lower priority.
            assert _request(inbound, port=53) in {"A1", "A2"}
            assert _dns_udp(inbound) in {"A1", "A2"}
            assert _request(inbound, port=direct.server_address[1], address="127.0.0.1") == "DIRECT"
            assert _request(inbound, address="192.0.2.1") not in {node.name for node in nodes}
            assert nodes[3].user_attempts == nodes[4].user_attempts == 0
            nodes[0].alive = False
            _round(nodes)
            _expect(inbound, {"A2"})
            nodes[1].alive = False
            _round(nodes)
            _expect(inbound, {"A3"})  # Slow but live A still outranks B.
            nodes[2].alive = False
            _round(nodes)
            _expect(inbound, {"B1"})
            assert _request(inbound, port=53) == "B1"
            assert _dns_udp(inbound) == "B1"
            nodes[3].alive = False
            _round(nodes)
            _expect(inbound, {"B2"})
            nodes[1].alive = True
            _round(nodes)
            _expect(inbound, {"A2"})
            assert _dns_udp(inbound) == "A2"
            nodes[1].alive = False
            nodes[4].alive = False
            _round(nodes)
            _round(nodes)  # discard any successful probe started before the state change
            attempts = [node.user_attempts for node in nodes]
            _expect(inbound, {None})
            assert _request(inbound, port=53) is None
            with pytest.raises(socket.timeout):
                _dns_udp(inbound)
            assert [node.user_attempts for node in nodes] == attempts
            # Deliberate direct exceptions survive; failed proxy/DNS never use them.
            assert _request(inbound, port=direct.server_address[1], address="127.0.0.1") == "DIRECT"
        logs = log_path.read_text(encoding="utf-8")
        assert "cf-to-a-check" in logs and "cf-to-pool-b" in logs and "cf-unavailable" in logs
    finally:
        gate.set()
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
        for node in nodes:
            node.close()
        direct.shutdown()
        direct.server_close()
        direct_thread.join(timeout=2)


@pytest.mark.parametrize("fix", [lambda x: x, apply_ios_fix, apply_ios_fix_dns], ids=["passthrough", "ios-fix", "ios-fix-dns"])
@pytest.mark.parametrize("fault", ["no-route", "balancer-error"])
def test_description_default_blocks_tcp_udp_and_dns(xray_binary, tmp_path, fix, fault):
    config = fix(compose_allowlist_balancer(json.loads(FIXTURE.read_text(encoding="utf-8")))[0])
    assert config["outbounds"][0]["tag"] == DESCRIPTION
    # Inject routing failures after normal validation to exercise the core's
    # default handler, not a supported way of configuring the middleware graph.
    config.pop("observatory")
    config.pop("dns", None)
    config["routing"] = {"rules": []}
    if fault == "balancer-error":
        config["routing"] = {
            "rules": [{"type": "field", "network": "tcp,udp", "balancerTag": "empty"}],
            "balancers": [{"tag": "empty", "selector": ["no-matching-outbound"], "strategy": {"type": "roundRobin"}}],
        }
    # Even accidental use of a real member can only hit loopback in this test.
    for outbound in config["outbounds"]:
        for server in outbound.get("settings", {}).get("vnext", []):
            server["address"], server["port"] = "127.0.0.1", 9
    inbound = _port()
    config["inbounds"] = [config["inbounds"][0]]
    config["inbounds"][0]["port"] = inbound
    config["log"] = {"loglevel": "info"}
    path = tmp_path / "fault.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    log_path = tmp_path / "fault.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(xray_binary), "run", "-c", str(path)], stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = time.monotonic() + 5
            while True:
                assert process.poll() is None, log_path.read_text(encoding="utf-8")
                try:
                    with socket.create_connection(("127.0.0.1", inbound), timeout=.2):
                        break
                except OSError:
                    assert time.monotonic() < deadline
                    time.sleep(.02)
            assert _request(inbound) is None
            assert _request(inbound, port=53) is None
            with pytest.raises(socket.timeout):
                _dns_udp(inbound)
        finally:
            process.terminate()
            process.wait(timeout=10)
    logs = log_path.read_text(encoding="utf-8")
    assert "cf-description" in logs
    assert "redirecting request tcp:127.0.0.1:9 to cf-unavailable" in logs
