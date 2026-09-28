"""PR-3 (2026-09-28): the momentum-scalp lane has an alarm that sees the truth.

Before: the lane log said PASS for ten days while Finviz was never refreshed; no collector asked
"did the refresh run?". Now `collect_momentum_scalp_refresh_age` reads the STARTED/DONE/FAILED
receipt written by momentum_scalp_early_lane_runner, and the existing scan assessor treats
"skipped_finviz_refresh on every run for >30 min in-window" as a finding.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import health_agent as ha  # noqa: E402

# No COVERS: this test exercises health-agent COLLECTORS, not Telegram alarm sites; claiming
# whole-file alarm coverage of health_agent.py would be false (tests/test_alarm_coverage.py).
A = ha._assess_refresh_receipt


def test_off_window_is_silent():
    assert A(None, None, False, 20) == {"finding": False, "reason": "off_window"}
    assert A(500, "DONE", False, 20)["finding"] is False


def test_no_receipt_in_window_is_a_finding():
    a = A(None, None, True, 20)
    assert a["finding"] and a["type"] == "momentum_scalp_refresh_missing" and a["severity"] == "warning"


def test_started_without_done_is_killed_after_threshold():
    assert A(None, "STARTED", True, 20, started_age_min=3)["finding"] is False
    a = A(None, "STARTED", True, 20, started_age_min=12)
    assert a["type"] == "momentum_scalp_refresh_killed"


def test_done_age_thresholds():
    assert A(5, "DONE", True, 20)["finding"] is False
    w = A(25, "DONE", True, 20); assert w["type"] == "momentum_scalp_refresh_stale" and w["severity"] == "warning"
    c = A(70, "DONE", True, 20); assert c["severity"] == "critical"


def test_failed_receipt_is_a_finding():
    assert A(None, "FAILED", True, 20)["type"] == "momentum_scalp_refresh_failed"


def test_policy_declares_thresholds():
    pol = json.loads((ROOT / "config/health_agent_policy.json").read_text())["momentum_scalp_refresh"]
    assert pol["enabled"] is True and pol["stale_min"] == 20 and pol["killed_after_min"] == 10


def test_collector_reads_receipt_through_the_lane_module(monkeypatch):
    now = datetime(2026, 9, 28, 10, 30, tzinfo=timezone.utc)
    stub = types.ModuleType("momentum_scalp_early_lane_runner")
    stub.now_et = lambda stamp=None: now
    stub.is_trading_day = lambda t: True
    stub.in_window = lambda t, w=None: True
    stub.read_refresh_receipt = lambda: {"state": "DONE", "at": (now - timedelta(minutes=40)).isoformat()}
    stub.refresh_age_min = lambda t=None, rec=None: 40.0
    monkeypatch.setitem(sys.modules, "momentum_scalp_early_lane_runner", stub)
    out = ha.collect_momentum_scalp_refresh_age()
    assert len(out) == 1 and out[0]["type"] == "momentum_scalp_refresh_stale" and out[0]["category"] == "pipeline_freshness"
    assert out[0]["receipt"]["state"] == "DONE"
    stub.read_refresh_receipt = lambda: {"state": "DONE", "at": (now - timedelta(minutes=4)).isoformat()}
    stub.refresh_age_min = lambda t=None, rec=None: 4.0
    assert ha.collect_momentum_scalp_refresh_age() == []


def test_collector_is_registered():
    assert ha.collect_momentum_scalp_refresh_age in ha.COLLECTORS


# ---- the existing scan assessor now sees "skipped forever"

def _line(gen_at, ran, reason=None):
    st = {"stage": "finviz_scan", "ran": ran}
    if reason: st["reason"] = reason
    return json.dumps({"generated_at": gen_at.isoformat(), "status": "PASS", "stages": [st]})


def test_skipped_refresh_span_counts_consecutive_skips_only():
    now = datetime(2026, 9, 28, 10, 30, tzinfo=timezone.utc)
    lines = [_line(now - timedelta(minutes=m), False, "skipped_finviz_refresh") for m in (50, 45, 40, 35, 30, 25, 20, 15, 10, 5)]
    assert round(ha._skipped_refresh_span_min(lines, now)) == 50
    lines2 = lines[:5] + [_line(now - timedelta(minutes=22), True)] + lines[6:]
    assert round(ha._skipped_refresh_span_min(lines2, now)) == 20
    assert ha._skipped_refresh_span_min([_line(now - timedelta(minutes=3), True)], now) is None
    fresh = [_line(now - timedelta(minutes=4), False, "skipped_finviz_refresh_fresh (age=4.0m < 15m)")]
    assert round(ha._skipped_refresh_span_min(fresh, now)) == 4   # fresh-skip still counts toward the span


def test_scan_assessor_flags_a_lane_that_never_refreshes():
    a = ha._assess_momentum_scalp_scan(3, "PASS", [], True, True, skipped_refresh_min=45)
    assert a["type"] == "momentum_scalp_refresh_never_runs"
    assert ha._assess_momentum_scalp_scan(3, "PASS", [], True, True, skipped_refresh_min=10)["finding"] is False
    assert ha._assess_momentum_scalp_scan(3, "PASS", [], True, True)["finding"] is False
