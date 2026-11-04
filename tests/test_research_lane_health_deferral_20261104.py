"""A deferred-to-offpeak run is not a lane error (2026-11-04).

`[DEFERRED_TO_OFFPEAK]` rows were counted as failures by `is_error_recommendation`, producing the bogus
37.9% 24h error rate that floored intelligence_quality at 60. The run was never attempted — like a budget
throttle, it is a deferral, and it must leave both the error count and the judged denominator.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import research_lane_health as h  # noqa: E402

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
DEFERRED = "[DEFERRED_TO_OFFPEAK]: job-1 on research (off-peak) — queued as rq-9, runs after 2026-11-04T23:00"


def _row(rec, minutes):
    return {"recommendation": rec, "created_at": (NOW.timestamp() - minutes * 60)}


def test_a_deferral_is_not_an_error_recommendation():
    assert h.is_error_recommendation(DEFERRED) is False
    assert h.is_error_recommendation("[SKIPPED_BUDGET] cap") is False   # unchanged
    assert h.is_error_recommendation("[LANE_BROKEN] boom") is True      # unchanged


def test_deferrals_do_not_inflate_the_24h_error_rate():
    rows = [_row("BUY NVDA", 5), _row("WATCH SPY", 10)] + [_row(DEFERRED, m) for m in (15, 20, 25)]
    health = h.evaluate_lane("research", newest_first=rows[:1], last_24h=rows, silence=False, now=NOW)
    assert health["error_rate_24h"] == 0.0, health
    assert not [f for f in health.get("firing") or [] if f.startswith("error_rate_24h")], health
