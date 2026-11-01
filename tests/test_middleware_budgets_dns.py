import asyncio
import copy
import gzip
import zlib
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.services.upstream import UpstreamClient, UpstreamError
from app.transformers.ios_fix import apply_ios_fix, apply_ios_fix_dns

_CLIENT = httpx.AsyncClient


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False
        self.read = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.read += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def fetch(stream, headers=None, *, cap=64, timeout=1, status=200, requests=None):
    async def run():
        async def handle(request):
            if requests is not None:
                requests.append(request)
            return httpx.Response(status, headers=headers, stream=stream)
        client = _CLIENT(transport=httpx.MockTransport(handle))
        settings = Settings(_env_file=None, upstream_base_url="https://upstream.invalid",
                            max_upstream_body_bytes=cap, request_timeout_sec=timeout)
        with patch("app.services.upstream.httpx.AsyncClient", return_value=client):
            return await UpstreamClient(settings).fetch("syntheticToken1234")
    return asyncio.run(run())


@pytest.mark.parametrize("length", [None, "1", "64"])
def test_mid002_rejects_stream_one_decoded_byte_over_cap(length):
    stream = Chunks([b"a" * 32, b"b" * 32, b"x", b"unread"])
    with pytest.raises(UpstreamError):
        fetch(stream, {"content-length": length} if length else {})
    assert stream.closed
    assert stream.read <= 3


@pytest.mark.parametrize("encoding,encode", [("gzip", gzip.compress), ("deflate", zlib.compress)])
def test_mid002_decoded_cap_applies_to_compressed_body(encoding, encode):
    stream = Chunks([encode(b"A" * 65)])
    with pytest.raises(UpstreamError):
        fetch(stream, {"content-encoding": encoding, "content-length": "1"})
    assert stream.closed


def test_mid002_total_deadline_closes_slow_stream():
    stream = Chunks([b"a"] * 20, delay=.01)
    with pytest.raises(UpstreamError):
        fetch(stream, timeout=.025)
    assert stream.closed


def profile(rules=None, outbounds=None):
    return {"outbounds": outbounds or [{"tag": "proxy", "protocol": "vless"},
                                       {"tag": "direct", "protocol": "freedom"}],
            "routing": {"rules": rules or []}}


@pytest.mark.parametrize("extra", [{"domain": ["example.invalid"]}, {"ip": ["192.0.2.0/24"]},
    {"inboundTag": ["local"]}, {"source": ["192.0.2.1"]}, {"sourceIP": ["192.0.2.1"]},
    {"sourcePort": 1234}, {"protocol": ["dns"]}, {"user": ["synthetic"]}, {"attrs": "attrs['x']"},
    {"network": "tcp"}, {"network": "udp"}])
def test_mid004_specific_dns_does_not_suppress_general_rule(extra):
    exception = {"type": "field", "port": 53, "outboundTag": "direct", **extra}
    fallback = {"type": "field", "network": "tcp,udp", "outboundTag": "direct"}
    original = profile([exception, fallback])
    saved = copy.deepcopy(original)
    fixed = apply_ios_fix_dns(original)
    assert original == saved
    assert fixed["routing"]["rules"] == [exception, {"type": "field", "port": 53,
        "network": "tcp,udp", "outboundTag": "proxy"}, fallback]
    assert apply_ios_fix_dns(fixed) == fixed


def test_mid004_general_direct_fallback_does_not_hide_new_rule():
    fallback = {"type": "field", "network": "tcp,udp", "outboundTag": "direct"}
    rules = apply_ios_fix_dns(profile([fallback]))["routing"]["rules"]
    assert rules[0].get("port") == 53
    assert rules[1] == fallback


def test_mid004_no_proxy_does_not_invent_target():
    original = profile(outbounds=[{"protocol": "freedom", "tag": "direct"}])
    assert apply_ios_fix_dns(original) == apply_ios_fix(original)


def test_mid004_direct_alias_is_not_proxy_target():
    original = profile([{"type": "field", "domain": ["example.invalid"], "outboundTag": "vpn-sounding"}],
        [{"tag": "vpn-sounding", "protocol": "freedom"}, {"tag": "real-proxy", "protocol": "trojan"}])
    assert apply_ios_fix_dns(original)["routing"]["rules"][-1]["outboundTag"] == "real-proxy"


@pytest.mark.parametrize("encoding,encode", [("gzip", gzip.compress), ("deflate", zlib.compress),
    ("deflate", lambda body: zlib.compress(body, wbits=-zlib.MAX_WBITS))])
def test_mid002_valid_compressed_chunks_preserve_body_and_metadata(encoding, encode):
    wire = encode(b"synthetic-base64-body")
    stream = Chunks([wire[index:index+1] for index in range(len(wire))])
    requests = []
    result = fetch(stream, {"content-encoding": encoding, "content-type": "text/plain",
        "subscription-userinfo": "upload=1; download=2", "set-cookie": "private"}, requests=requests)
    assert result.body == "synthetic-base64-body"
    assert result.headers == {"content-type": "text/plain", "subscription-userinfo": "upload=1; download=2"}
    assert requests[0].headers["accept-encoding"] == "gzip, deflate, identity"
    assert requests[0].method == "GET"
    assert stream.closed


def test_mid002_gzip_concatenated_members_are_bounded():
    body = gzip.compress(b"first") + gzip.compress(b"second")
    assert fetch(Chunks([body]), {"content-encoding": "gzip"}).body == "firstsecond"
    with pytest.raises(UpstreamError):
        fetch(Chunks([body]), {"content-encoding": "gzip"}, cap=10)


@pytest.mark.parametrize("single_chunk", [True, False])
def test_mid002_raw_deflate_may_begin_with_valid_wrapped_header_bytes(single_chunk):
    wire = bytes.fromhex("780100feff41010000ffff")
    assert zlib.decompress(wire, -zlib.MAX_WBITS) == b"A"
    chunks = [wire] if single_chunk else [wire[i:i+1] for i in range(len(wire))]
    assert fetch(Chunks(chunks), {"content-encoding": "deflate"}).body == "A"


@pytest.mark.parametrize("split", [True, False])
def test_mid002_gzip_zero_padding_and_members_are_supported(split):
    wire = gzip.compress(b"A") + b"\x00" * 8 + gzip.compress(b"B") + b"\x00" * 8
    chunks = [wire[i:i+1] for i in range(len(wire))] if split else [wire]
    assert fetch(Chunks(chunks), {"content-encoding": "gzip"}).body == "AB"
    with pytest.raises(UpstreamError):
        fetch(Chunks([gzip.compress(b"A") + b"garbage"]), {"content-encoding": "gzip"})


@pytest.mark.parametrize("encoding,body", [("gzip", b"not-gzip"), ("deflate", b"invalid"),
    ("gzip", gzip.compress(b"data")[:-2]), ("br", b"unsupported"), ("gzip, deflate", b"unsupported")])
def test_mid002_invalid_or_unsupported_content_encoding_is_controlled(encoding, body):
    stream = Chunks([body])
    with pytest.raises(UpstreamError):
        fetch(stream, {"content-encoding": encoding})
    assert stream.closed


@pytest.mark.parametrize("content_type,body,expected", [
    ("text/plain; charset=iso-8859-1", b"caf\xe9", "caf\xe9"),
    ("text/plain; charset=not-an-encoding", b"a\xffb", "a\ufffdb"),
    ("text/plain; charset=utf-8", b"a\xffb", "a\ufffdb"),
])
def test_mid002_httpx_charset_semantics_preserved(content_type, body, expected):
    result = fetch(Chunks([body]), {"content-type": content_type})
    assert result.body == expected
    assert result.body == httpx.Response(200, content=body, headers={"content-type": content_type}).text


@pytest.mark.parametrize("status", [200, 204, 301, 400, 404, 500])
def test_mid002_empty_and_error_status_results_are_preserved(status):
    stream = Chunks([])
    result = fetch(stream, status=status)
    assert result.status_code == status
    assert result.body == ""
    assert stream.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
@pytest.mark.parametrize("status", [200, 204, 404])
def test_mid002_empty_body_with_encoding_header_preserves_httpx_behavior(encoding, status):
    assert fetch(Chunks([]), {"content-encoding": encoding}, status=status).body == ""


def test_mid004_webhook_metadata_does_not_make_broad_fallback_specific():
    fallback = {"type": "field", "network": "tcp,udp", "outboundTag": "direct", "webhook": "https://audit.invalid"}
    rules = apply_ios_fix_dns(profile([fallback]))["routing"]["rules"]
    assert rules[0]["port"] == 53
    assert rules[1] == fallback


def test_mid002_exact_cap_and_untrusted_large_content_length():
    stream = Chunks([b"a" * 64])
    result = fetch(stream, {"content-length": "99999999999"})
    assert len(result.body) == 64
    assert stream.closed


def test_mid002_default_cap_and_invalid_budget_settings():
    settings = Settings(_env_file=None)
    assert settings.max_upstream_body_bytes == 2097152
    for kwargs in ({"max_upstream_body_bytes": 0}, {"max_upstream_body_bytes": -1},
                   {"request_timeout_sec": 0}, {"request_timeout_sec": float("inf")}):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **kwargs)


def test_mid002_cancellation_propagates_and_closes_stream():
    class Cancelled(Chunks):
        async def __aiter__(self):
            yield b"a"
            raise asyncio.CancelledError()
    stream = Cancelled([])
    with pytest.raises(asyncio.CancelledError):
        fetch(stream)
    assert stream.closed


def test_mid002_wire_budget_stops_nonexpanding_compressed_stream():
    # Empty concatenated members still consume CPU/wire bytes, so have a budget.
    member = gzip.compress(b"")
    stream = Chunks([member] * 4000)
    with pytest.raises(UpstreamError, match="wire limit"):
        fetch(stream, {"content-encoding": "gzip"})
    assert stream.closed
    assert stream.read < 4000


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("size,status", [(64, 200), (65, 502)])
def test_mid002_route_get_and_head_share_body_budget(monkeypatch, method, size, status):
    from fastapi.testclient import TestClient
    from app.main import app
    stream = Chunks([b"a" * size])
    async def handle(request):
        assert request.method == "GET"  # HEAD still validates the upstream body.
        assert request.url.query == b"os=ios"
        assert request.headers["host"] == "panel.invalid"
        return httpx.Response(200, stream=stream, headers={"profile-title": "Synthetic"})
    settings = Settings(_env_file=None, upstream_base_url="https://upstream.invalid",
                        upstream_host_header="panel.invalid", max_upstream_body_bytes=64)
    monkeypatch.setattr(app.state, "settings", settings)
    with patch("app.services.upstream.httpx.AsyncClient", return_value=_CLIENT(transport=httpx.MockTransport(handle))):
        result = TestClient(app).request(method, "/json/syntheticToken1234?os=ios")
    assert result.status_code == status
    assert stream.closed
    if method == "HEAD":
        assert result.content == b""
    elif status == 200:
        assert result.content == b"a" * 64
        assert result.headers["profile-title"] == "Synthetic"


def test_mid002_default_two_mib_boundary_is_inclusive():
    cap = 2 * 1024 * 1024
    assert len(fetch(Chunks([b"a" * cap]), cap=cap).body) == cap
    with pytest.raises(UpstreamError):
        fetch(Chunks([b"a" * cap, b"x"]), cap=cap)


@pytest.mark.parametrize("protocol", ["vless", "vmess", "trojan", "shadowsocks", "socks", "http",
    "hysteria", "hysteria2", "wireguard", "tuic", "shadowsocks2022"])
def test_mid004_supported_proxy_protocol_can_be_target(protocol):
    result = apply_ios_fix_dns(profile(outbounds=[{"tag": "actual", "protocol": protocol}]))
    assert result["routing"]["rules"][0]["outboundTag"] == "actual"


@pytest.mark.parametrize("protocol", ["freedom", "dns", "blackhole", "loopback", "unknown", ""])
def test_mid004_system_and_unknown_protocol_never_invent_proxy(protocol):
    original = profile(outbounds=[{"tag": "proxy", "protocol": protocol}])
    assert apply_ios_fix_dns(original) == apply_ios_fix(original)


@pytest.mark.parametrize("tag", ["proxy", "direct"])
@pytest.mark.parametrize("network", [None, "tcp,udp", "udp,tcp"])
def test_mid004_existing_reachable_full_dns_policy_preserved(tag, network):
    rule = {"type": "field", "port": "53", "outboundTag": tag}
    if network:
        rule["network"] = network
    original = profile([rule])
    assert apply_ios_fix_dns(original)["routing"]["rules"] == [rule]


def test_mid004_existing_unreachable_dns_does_not_prevent_insertion():
    fallback = {"type": "field", "network": "tcp,udp", "outboundTag": "direct"}
    dns = {"type": "field", "port": 53, "outboundTag": "direct"}
    rules = apply_ios_fix_dns(profile([fallback, dns]))["routing"]["rules"]
    assert rules[0]["port"] == 53
    assert rules[0]["outboundTag"] == "proxy"
    assert rules[1:] == [fallback, dns]


def test_mid004_balancer_members_and_fallback_must_be_real_proxy_targets():
    original = profile()
    original["routing"]["balancers"] = [{"tag": "bad", "selector": ["direct"]},
        {"tag": "good", "selector": ["proxy"]}]
    result = apply_ios_fix_dns(original)
    assert result["routing"]["rules"][0]["balancerTag"] == "good"


def test_mid004_dangling_rule_tag_is_not_selected():
    original = profile([{"port": 53, "domain": ["example.invalid"], "outboundTag": "absent"}])
    rules = apply_ios_fix_dns(original)["routing"]["rules"]
    assert rules[0]["outboundTag"] == "absent"  # Existing exception not rewritten.
    assert rules[1]["outboundTag"] == "proxy"


def test_mid004_specific_non_dns_exclusions_precede_general_dns():
    exceptions = [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
        {"type": "field", "domain": ["geosite:private"], "outboundTag": "direct"},
        {"type": "field", "port": "443", "outboundTag": "direct"}]
    fallback = {"type": "field", "network": "tcp,udp", "outboundTag": "direct"}
    fixed = apply_ios_fix_dns(profile(exceptions + [fallback]))
    assert fixed["routing"]["rules"][:3] == exceptions
    assert fixed["routing"]["rules"][3]["port"] == 53
    assert fixed["routing"]["rules"][4] == fallback


def test_mid004_allowlist_graph_unchanged():
    import json
    from pathlib import Path
    from app.features.allowlist_balancer import compose_allowlist_balancer
    payload = json.loads((Path(__file__).parent / "fixtures" / "priority_pools_3xui.json").read_text(encoding="utf-8"))
    composed = compose_allowlist_balancer(payload)
    assert apply_ios_fix_dns(composed) == apply_ios_fix(composed)
    assert apply_ios_fix_dns(apply_ios_fix_dns(composed)) == apply_ios_fix_dns(composed)
