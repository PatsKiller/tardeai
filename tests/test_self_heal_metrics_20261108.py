"""SELF_HEAL_METRICS_SAFETY_20261108 - metrics: funnel, false-fix-7d, cost per accepted, MTTR. Hermetic."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.lib import self_heal_metrics as m  # noqa: E402

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def r(job, state, hours_ago, cost=None, inc_hours_ago=None):
    row = {"job_id": job, "lane": "L", "state": state, "at": (NOW - timedelta(hours=hours_ago)).isoformat(), "cost_usd": cost}
    if inc_hours_ago is not None:
        row["incident_at"] = (NOW - timedelta(hours=inc_hours_ago)).isoformat()
    return row


def test_funnel_counts_distinct_jobs():
    rows = [r("a", "fix_requested", 50), r("a", "fix_ready_local", 40, 2.0), r("a", "fix_deployed", 30), r("a", "output_recovered", 20),
            r("b", "fix_requested", 50), r("b", "insufficient_evidence", 49), r("c", "fix_requested", 5), r("c", "fix_ready_local", 4, 4.0)]
    s = m.summarize(rows, NOW)
    assert (s["admitted"], s["insufficient_evidence"], s["accepted"], s["deployed"], s["output_recovered"]) == (3, 1, 2, 1, 1)


def test_cost_per_accepted_never_counts_unknown_as_zero():
    rows = [r("a", "fix_ready_local", 3, 2.0), r("b", "fix_ready_local", 3, None)]
    s = m.summarize(rows, NOW)
    assert s["cost_per_accepted"] == 1.0 and s["cost_unknown_jobs"] == 1
    assert m.summarize([r("b", "fix_ready_local", 3, None)], NOW)["cost_per_accepted"] is None


def test_false_fix_needs_recurrence_inside_7d_of_heal():
    rows = [r("a", "output_recovered", 48), r("a", "recurred", 24),
            r("b", "output_recovered", 48), r("c", "output_recovered", 400), r("c", "recurred", 1)]
    s = m.summarize(rows, NOW)["false_fix_7d"]
    assert s == {"healed": 2, "false": 1, "rate": 0.5}  # c healed outside the window; its recurrence is not counted
    assert m.summarize([], NOW)["false_fix_7d"]["rate"] is None


def test_mttr_hours_and_none():
    rows = [r("a", "output_recovered", 10, inc_hours_ago=14), r("b", "incident_resolved", 5, inc_hours_ago=9)]
    assert m.summarize(rows, NOW)["mttr_h"] == 4.0
    assert m.summarize([r("a", "fix_requested", 1)], NOW)["mttr_h"] is None


def test_bad_rows_are_skipped_and_append_roundtrips(tmp_path):
    p = tmp_path / "x" / "metrics.jsonl"
    m.append_row(r("a", "fix_requested", 1), p)
    with p.open("a") as fh:
        fh.write("{torn\n")
    m.append_row({"job_id": "b", "state": "fix_requested", "at": "garbage"}, p)
    rows = m.read_rows(p)
    assert len(rows) == 2 and m.summarize(rows, NOW)["admitted"] == 1
    assert m.read_rows(tmp_path / "none.jsonl") == []
