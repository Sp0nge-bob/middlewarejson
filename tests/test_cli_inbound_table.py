from app.cli import _format_endpoint


def test_format_endpoint_address_and_port() -> None:
    row = {"address": "node1.example.com", "port": 443}
    assert _format_endpoint(row) == "node1.example.com:443"


def test_format_endpoint_port_only() -> None:
    row = {"address": "", "port": 443}
    assert _format_endpoint(row) == "порт 443"


def test_format_endpoint_empty() -> None:
    row = {"address": "", "port": 0}
    assert _format_endpoint(row) == "—"