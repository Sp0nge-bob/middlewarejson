from datetime import timedelta

import pytest

from app.services.panel_sync import parse_sync_interval


def test_parse_sync_interval_hours() -> None:
    assert parse_sync_interval("24h") == timedelta(hours=24)
    assert parse_sync_interval("12H") == timedelta(hours=12)


def test_parse_sync_interval_days() -> None:
    assert parse_sync_interval("7d") == timedelta(days=7)


def test_parse_sync_interval_minutes() -> None:
    assert parse_sync_interval("30m") == timedelta(minutes=30)


def test_parse_sync_interval_empty() -> None:
    assert parse_sync_interval("") is None
    assert parse_sync_interval("   ") is None


def test_parse_sync_interval_invalid() -> None:
    with pytest.raises(ValueError):
        parse_sync_interval("bad")
    with pytest.raises(ValueError):
        parse_sync_interval("0h")
    with pytest.raises(ValueError):
        parse_sync_interval("24")