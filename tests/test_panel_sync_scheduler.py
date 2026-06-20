from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.panel_sync import next_sync_at, parse_sync_time


def test_parse_sync_time_valid() -> None:
    assert parse_sync_time("04:00") == (4, 0)
    assert parse_sync_time("23:59") == (23, 59)


def test_parse_sync_time_empty() -> None:
    assert parse_sync_time("") is None
    assert parse_sync_time("   ") is None


def test_parse_sync_time_invalid() -> None:
    with pytest.raises(ValueError):
        parse_sync_time("25:00")
    with pytest.raises(ValueError):
        parse_sync_time("bad")


def test_next_sync_at_same_day() -> None:
    tz = ZoneInfo("UTC")
    now = datetime(2026, 6, 20, 3, 0, tzinfo=tz)
    target = next_sync_at(now, 4, 0)
    assert target == datetime(2026, 6, 20, 4, 0, tzinfo=tz)


def test_next_sync_at_next_day() -> None:
    tz = ZoneInfo("UTC")
    now = datetime(2026, 6, 20, 5, 0, tzinfo=tz)
    target = next_sync_at(now, 4, 0)
    assert target == datetime(2026, 6, 21, 4, 0, tzinfo=tz)