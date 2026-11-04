"""Trading-session age, with independent close-time boundary examples."""
from datetime import datetime
import importlib.util
from pathlib import Path
import sys

import pytest


SPEC = importlib.util.spec_from_file_location(
    "_fq116_stop_session_evidence",
    Path(__file__).resolve().parents[1] / "scripts/lib/stop_session_evidence.py")
evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evidence
SPEC.loader.exec_module(evidence)


@pytest.mark.parametrize("observed,now,status,count,minimum", [
    ("2026-11-04T14:59:00Z", "2026-11-04T15:00:00Z", "FRESH", 0, None),
    # Friday close counts, Saturday/Sunday do not; DST changes on this weekend.
    ("2026-10-30T19:00:00Z", "2026-11-02T14:00:00Z", "FRESH", 1, None),
    ("2026-10-30T20:01:00Z", "2026-11-02T14:00:00Z", "FRESH", 0, None),
    ("2026-10-29T19:00:00Z", "2026-11-02T14:00:00Z", "STALE", None, 2),
    # Thanksgiving is closed. The following Friday closes at 13:00 ET.
    ("2026-11-25T20:00:00Z", "2026-11-27T17:59:00Z", "FRESH", 1, None),
    ("2026-11-25T20:00:00Z", "2026-11-27T18:00:00Z", "STALE", None, 2),
    # An observation AT a close already includes that completed session.
    ("2026-11-25T21:00:00Z", "2026-11-27T18:00:00Z", "FRESH", 1, None),
    ("2026-11-04T21:00:00Z", "2026-11-04T21:00:00Z", "FRESH", 0, None),
    ("2025-01-02T17:00:00Z", "2026-11-04T15:00:00Z", "STALE", None, 2),
    ("2026-11-04T09:59:00-05:00", "2026-11-04T15:00:00Z", "FRESH", 0, None),
])
def test_completed_sessions(observed, now, status, count, minimum):
    result = evidence.stop_observation_freshness(observed, now=now)
    assert result["status"] == status
    assert result["completed_sessions_since"] == count
    assert result["completed_sessions_at_least"] == minimum
    assert result["as_of"].endswith("Z")
    assert bool(result["reason"]) is (status != "FRESH")


@pytest.mark.parametrize("observed", [None, "", "broken", "2026-11-04",
                                      "2026-11-04T14:59:00", {}, 1793800000,
                                      datetime(2026, 11, 4, 14, 59),
                                      "2026-11-04T15:00:00.000001Z"])
def test_missing_invalid_zoneless_and_future_observations_refuse(observed):
    result = evidence.stop_observation_freshness(observed, now="2026-11-04T15:00:00Z")
    assert result["status"] == "UNAVAILABLE"
    assert result["completed_sessions_since"] is None
    assert result["reason"]


@pytest.mark.parametrize("now", [None, "broken", "2026-11-04T15:00:00"])
def test_unknown_current_clock_refuses(now):
    result = evidence.stop_observation_freshness("2026-11-04T14:59:00Z", now=now)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "Current time is unavailable"
