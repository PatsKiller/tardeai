"""The SETUPS session-stale finding compares run_date to the session that should be current, not the calendar.

Since 2026-10-12 (0b22fdfac) heal_trade_ai_session_cache.py anchors session_date only and never rewrites run_date,
so `run_date < today` could never clear before the first scan, on weekends or on holidays, and the Health Agent
heal was marked ineffective for days (2026-10-31 stuck sweep). Hermetic: fixed clocks, NYSE calendar from code.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts import health_agent as ha

ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _policy(monkeypatch):
    monkeypatch.setattr(ha, "load_policy", lambda: {"setups_session": {"first_full_scan_et": "09:30"}})


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 31, 11, 0, tzinfo=ET), "2026-10-30"),  # Saturday -> Friday
        (datetime(2026, 11, 1, 20, 0, tzinfo=ET), "2026-10-30"),  # Sunday -> Friday
        (datetime(2026, 11, 2, 7, 0, tzinfo=ET), "2026-10-30"),  # Monday before the first scan -> Friday
        (datetime(2026, 11, 2, 10, 0, tzinfo=ET), "2026-11-02"),  # Monday after the first scan -> today
        (datetime(2026, 11, 27, 8, 0, tzinfo=ET), "2026-11-25"),  # day after Thanksgiving, pre-scan -> Wednesday
    ],
)
def test_expected_run_date(now, expected):
    assert ha.expected_setups_run_date(now) == expected


def test_friday_run_is_not_stale_on_saturday(monkeypatch, tmp_path):
    cache = tmp_path / "data" / "runtime" / "trade_ai_cache.json"
    cache.parent.mkdir(parents=True)
    cache.write_text('{"run_date": "2026-10-30", "session_date": "2026-10-31"}')
    monkeypatch.setattr(ha, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ha, "expected_setups_run_date", lambda now=None: "2026-10-30")
    assert not [f for f in ha.collect_trade_ai_session() if f.get("type") == "trade_ai_session_stale"]
    monkeypatch.setattr(ha, "expected_setups_run_date", lambda now=None: "2026-11-02")
    assert [f for f in ha.collect_trade_ai_session() if f.get("type") == "trade_ai_session_stale"]
