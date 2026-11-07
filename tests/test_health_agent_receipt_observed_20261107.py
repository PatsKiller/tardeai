"""A review that reports the system's failures is not a review that failed.

WORK-QUEUE item 8, 2026-11-07. ``health-agent-llm-review`` ran at 01:30Z, stored its review
(``status: stored``, ``response_chars: 3271``, exit 0, ``ok_at`` set) — and was graded **DEGRADED**
for this receipt:

    summary {"status":"stored","response_chars":3271,"health_events":100,"failed_jobs":7,
             "interventions":10,"pipeline_failed":13}

``lib.run_quality.receipt_flags`` reads any top-level summary key ending in ``failed`` as *this
run's* failure count, so the 13 failed pipeline runs the review OBSERVED read as 13 reviews that
failed. The count is a measurement of the subject, not a defect of the review (the same class the
reader already handles for ``stale``/``degraded`` under ``_SUBJECT_COUNTERS``).

The fix keeps the measurement in the receipt — count, 24 h window and the pipelines that failed —
but under ``observed``, so the lane's own outcome is what the top level states. Tested hermetically:
no DB, no model, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import health_agent_llm_review as h   # noqa: E402
from lib import run_quality as rq     # noqa: E402

OLD_RESULT = {"status": "stored", "response_chars": 3271, "health_events": 100,
              "failed_jobs": 7, "interventions": 10, "pipeline_failed": 13,
              "pipeline_total": 1198,
              "pipeline_failed_by_key": [{"pipeline": "process_watchlist_agent_jobs", "failed": 5},
                                         {"pipeline": "rag_indexer", "failed": 3}]}


def _old_receipt():
    """The receipt shape the lane wrote on 2026-11-07 01:30Z — summary was the raw result."""
    return {"lane_id": "health-agent-llm-review", "status": "ok", "exit": 0,
            "summary": dict(OLD_RESULT)}


def test_the_old_shape_really_was_flagged_as_the_lanes_own_failure():
    """The defect, stated by the reader itself — this is the line the queue quoted."""
    assert "summary reports pipeline_failed = 13" in rq.receipt_flags(_old_receipt())


def test_the_new_shape_keeps_the_measurement_and_drops_the_false_flag():
    summary = h._receipt_summary(OLD_RESULT)
    receipt = {"lane_id": "health-agent-llm-review", "status": "ok", "exit": 0, "summary": summary}

    assert rq.receipt_flags(receipt) == []

    # Nothing is hidden: the count, the window and WHICH pipelines failed all survive.
    assert summary["status"] == "stored" and summary["response_chars"] == 3271
    obs = summary["observed"]
    assert obs["health_events"] == 100 and obs["failed_jobs"] == 7
    assert obs["pipeline_runs"] == {
        "window_hours": 24, "total": 1198, "failed": 13,
        "failed_by_key": OLD_RESULT["pipeline_failed_by_key"]}


def test_the_lanes_own_outcome_survives_the_reshape():
    """The change must not mute the review's own status — only move what it measured."""
    for status in ("stored", "no_response", "store_failed"):
        summary = h._receipt_summary({"status": status, "pipeline_failed": 0})
        assert summary["status"] == status


def test_a_missing_pipeline_account_is_not_invented():
    summary = h._receipt_summary({"status": "stored", "response_chars": 10})
    assert summary == {"status": "stored", "response_chars": 10}


def test_the_receipt_never_carries_a_bare_top_level_failure_counter():
    summary = h._receipt_summary(OLD_RESULT)
    flagged = [k for k in summary if rq._ERROR_KEY.search(k.lower())]
    assert flagged == []


# ── the collector names the pipelines it counted ────────────────────────────

class _Cur:
    def __init__(self, script):
        self._script = script
        self.i = 0
        self._rows = []

    def execute(self, sql, params=None):
        self._rows = self._script[self.i]
        self.i += 1

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, script):
        self._cur = _Cur(script)

    def cursor(self):
        return self._cur


def test_the_collector_records_which_pipelines_failed():
    """A bare 13 cannot be acted on; the receipt has to be able to say which lanes and how many."""
    script = [
        [],                                                          # health events
        [("maria", 10, "2026-11-06")],                               # agent activity
        [("maria", 4)],                                              # failed jobs
        [(13, 1198)],                                                # pipeline failed/total
        [("process_watchlist_agent_jobs", 5), ("rag_indexer", 3)],   # failed by key
        [],                                                          # interventions
        [(3, 1, 0)],                                                 # paper trades
    ]
    data = h._collect_daily_health_data(_Conn(script))
    assert data["pipeline"]["failed"] == 13 and data["pipeline"]["total"] == 1198
    assert data["pipeline"]["failed_by_key"] == [
        {"pipeline": "process_watchlist_agent_jobs", "failed": 5},
        {"pipeline": "rag_indexer", "failed": 3}]


def test_the_dry_run_still_states_the_counts_without_a_receipt(monkeypatch, capsys):
    assert h.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN health-agent-llm-review" in out
