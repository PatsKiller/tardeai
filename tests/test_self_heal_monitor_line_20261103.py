"""Self-heal hourly block: the counts and the one-line verdict (operator request, 2026-11-03).

The block answers "is self-healing live and working" in one paste for the hourly email:
detected / dispatched / fixed / still blocked from the supervisor receipt and the incident
index, plus DETECT / DECIDE / FIX and a single lane verdict. Pure builder — fixtures only.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.self_heal_monitor_line import build_block  # noqa: E402

NOW = datetime(2026, 11, 3, 17, 7, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _index():
    return {
        "summary": {"counts": {"open": 10, "fixed": 529, "blocked": 27}, "unresolved": 10},
        "incidents": [
            {"id": "NEW1", "status": "open", "opened_at": _iso(NOW - timedelta(minutes=5))},
            {"id": "NEW2", "status": "fixed", "opened_at": _iso(NOW - timedelta(minutes=20)),
             "closed_at": _iso(NOW - timedelta(minutes=2))},
            {"id": "OLD", "status": "blocked", "opened_at": _iso(NOW - timedelta(days=2))},
            {"id": "FIXED-OLD", "status": "fixed", "opened_at": _iso(NOW - timedelta(days=1)),
             "closed_at": _iso(NOW - timedelta(hours=3))},
        ],
    }


def _watchers(as_of=None, gap=None):
    return {"as_of": _iso(as_of or NOW - timedelta(minutes=2)),
            "watchers": {"health_tick": {"findings": 3, "gap": None},
                         "lane_health": {"findings": 16, "gap": gap}}}


def _supervisor(skips=("daily model-call cap",) * 5, dispatched=0, actions=0):
    return {"as_of": _iso(NOW - timedelta(minutes=3)), "considered": [f"INC{i}" for i in range(5)],
            "actions": [{}] * actions, "dispatched": [{}] * dispatched, "skipped": [{"why": w} for w in skips]}


def _fixer(state="fix_requested", n=5):
    return {"jobs": {f"job{i}": {"state": state} for i in range(n)}}


def test_starved_lane_reports_counts_and_the_cap():
    block = build_block(index=_index(), supervisor=_supervisor(), watchers=_watchers(), calls={"count": 40},
                        policy={"policy": {"max_model_calls_per_day": 40}}, fixer=_fixer(), now=NOW)
    assert block[0] == "SELF-HEAL · 17:07 UTC"
    assert block[1] == ("detected 2 (last hour) · dispatched 0 · fixed 1 (last hour) · "
                        "still blocked 27 · unresolved 10")
    assert "considered 5, actions 0, dispatched 0, skipped 5 (5 on daily model-call cap)" in block[2]
    assert "model calls today 40/40" in block[2]
    assert block[3].startswith("watchers ") and "2/2 without a gap" in block[3]
    assert block[4].startswith("verdict: NOT LIVE — DETECT alive · DECIDE starved by the daily model-call cap")
    assert block[4].endswith("FIX not scheduled (5 requests queued)")


def test_a_working_lane_says_alive_end_to_end():
    block = build_block(index=_index(), supervisor=_supervisor(skips=(), dispatched=2, actions=1),
                        watchers=_watchers(), calls={"count": 3},
                        policy={"policy": {"max_model_calls_per_day": 240}}, fixer=_fixer(n=0), now=NOW)
    assert "dispatched 2" in block[1]
    assert "skipped 0 (0 on daily model-call cap)" in block[2]
    assert block[4] == ("verdict: LIVE — DETECT alive · DECIDE working · FIX no queue")


def test_a_watcher_gap_is_reported_not_hidden():
    block = build_block(index=_index(), supervisor=_supervisor(skips=()), watchers=_watchers(gap={"reason": "unreadable"}),
                        calls={"count": 0}, policy={"policy": {"max_model_calls_per_day": 240}},
                        fixer=_fixer(n=0), now=NOW)
    assert "1/2 without a gap" in block[3]
    assert block[4].startswith("verdict: NOT LIVE — DETECT stale/gapped")


def test_a_stale_watcher_receipt_is_not_alive():
    block = build_block(index=_index(), supervisor=_supervisor(skips=()),
                        watchers=_watchers(as_of=NOW - timedelta(hours=1)), calls={"count": 0},
                        policy={"policy": {"max_model_calls_per_day": 240}}, fixer=_fixer(n=0), now=NOW)
    assert block[4].startswith("verdict: NOT LIVE — DETECT stale/gapped")


def test_missing_inputs_still_produce_a_block():
    block = build_block(index={}, supervisor={}, watchers={}, calls={}, policy={}, fixer={}, now=NOW)
    assert "detected 0 (last hour)" in block[1] and "still blocked 0" in block[1]
    assert "model calls today ?/40" in block[2]
    assert block[4].startswith("verdict: NOT LIVE — DETECT stale/gapped")
