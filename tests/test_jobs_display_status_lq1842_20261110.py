"""LQ-20261107-1842: "running on schedule" is not green when the job's own quality grade is not GOOD.

Three defects, one page (CC v3 due-diligence findings #5, #15, #16; measured 2026-11-10T21:20Z on the live
``/api/v2/jobs-history``, 717 rows / 508 ACTIVE, read-only):

1. 104 ACTIVE rows were status ``ok`` — the UI's green "Running on schedule" — while their quality grade was not
   GOOD (UNPROVEN 60, DEGRADED 16, NOT_LIVE 16, EMPTY 12). A green card next to a non-GOOD grade is the page
   contradicting reality.
2. A run that correctly had nothing to do (its receipt states a reviewed no-work reason: no_pending_events,
   all_already_settled, below_trigger, …) graded EMPTY or GOOD·idle — one read as a defect, the other as green.
   It gets its own grade, IDLE: not Good (it produced nothing), not Empty (nothing is wrong), never green.
3. The row status ``degraded`` counted 0 while 19 rows were graded DEGRADED — two grades, one word. The row
   status is renamed ``subject_degraded`` (the last run reports a degraded SUBJECT); DEGRADED keeps the word.

Synthetic rows, lanes and receipts only — the repo is PUBLIC. No state root is read; no network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import jobs_history as J
from scripts.lib import run_quality as Q

NOW = datetime(2026, 11, 10, 21, 20, tzinfo=timezone.utc)
START = NOW - timedelta(seconds=60)
FINISH = NOW - timedelta(seconds=30)

LANE = {"lane_id": "synthetic-lane", "state": "ACTIVE", "scheduler": {"kind": "n8n"},
        "output_signal": {"kind": "json_key", "path": "data/runtime/synthetic_last.json", "key": "ok_at"}}
RUN = {"mode": "live", "result": "succeeded", "started_at": START.isoformat(), "finished_at": FINISH.isoformat(),
       "duration_s": 30.0, "run_id": "r1", "exit_code": 0, "reason": None, "source": "n8n run ledger"}
ROW = {"lane_id": "synthetic-lane", "state": "ACTIVE", "status": "ok", "runs": [RUN], "last_run": RUN}


def receipt(**extra):
    doc = {"schema": "LaneRunReceipt@v2", "mode": "live", "status": "ok", "exit": 0,
           "started_at": START.isoformat(), "finished_at": FINISH.isoformat()}
    doc.update(extra)
    return doc


def _grade(doc, *, output_at=FINISH):
    ev = {"receipt": doc, "receipt_path": None, "output_at": output_at, "ledger": [], "history": [],
          "contract": None, "freshness": [], "freshness_known": True, "plausibility": [],
          "plausibility_known": True}
    return Q.grade(ROW, LANE, ev, now=NOW)


def job_row(*, status="ok", grade=None, headline=None, status_reason=None, lane_id="synthetic-lane"):
    """A jobs-history row with the given status and quality block (synthetic)."""
    row = {"lane_id": lane_id, "job": lane_id, "scheduler": "n8n", "state": "ACTIVE", "status": status,
           "status_reason": status_reason, "fix_count": 0,
           "cadence": {"expressions": ["*/30 * * * *"], "timezone": "America/New_York", "every_hours": 0.5,
                       "market_days_only": False}}
    if grade is not None:
        row["quality"] = {"grade": grade, "headline": headline or f"synthetic {grade} headline"}
    return row


# ── AC-1: green only when status ok AND quality GOOD ────────────────────────────────────────────────────────────

def test_green_requires_status_ok_and_grade_good():
    d = J.display_status(job_row(status="ok", grade="GOOD"))
    assert d["green"] is True and d["tone"] == "success"
    assert d["label"] == "Running on schedule" and d["reason"] is None


@pytest.mark.parametrize("grade", ["IDLE", "DEGRADED", "EMPTY", "FAILED", "NOT_LIVE", "UNPROVEN"])
def test_every_other_ok_grade_is_amber_naming_the_reason(grade):
    d = J.display_status(job_row(status="ok", grade=grade, headline=f"the run {grade.lower()}ed"))
    assert d["green"] is False, "an ok row whose result is not GOOD must never render green"
    assert d["tone"] == "warning"
    assert d["label"].startswith("Ran on time, result ")
    assert d["reason"] == f"the run {grade.lower()}ed"
    assert d["quality"] == grade


def test_an_ok_row_with_no_grade_is_amber_never_green():
    d = J.display_status(job_row(status="ok", grade=None))
    assert d["green"] is False and d["tone"] == "warning"
    assert d["reason"] == "no quality grade was computed for this run"


def test_the_amber_label_names_the_quality_word():
    assert J.display_status(job_row(grade="UNPROVEN"))["label"] == "Ran on time, result unproven"
    assert J.display_status(job_row(grade="IDLE"))["label"] == "Ran on time, result nothing to do"
    assert J.display_status(job_row(grade="EMPTY"))["label"] == "Ran on time, result empty"
    assert J.display_status(job_row(grade="NOT_LIVE"))["label"] == "Ran on time, result not live"


def test_a_non_ok_row_is_never_green():
    for status in ("failed", "blocked", "subject_degraded", "missed", "late", "running", "not_measured",
                   "paused", "retired", "never_scheduled"):
        d = J.display_status(job_row(status=status, grade="GOOD", status_reason="synthetic reason"))
        assert d["green"] is False, f"{status} must not be green even with a GOOD grade"
        assert d["reason"] == "synthetic reason"
        assert d["label"] == J.STATUS_LABEL[status]


# ── AC-2: IDLE, from the tokens real receipts state ─────────────────────────────────────────────────────────────

#: Every token below was observed in a real receipt on 2026-11-10 (data/runtime/*_last.json). The vocabulary is
#: the receipts' own, not invented, and each is registered in config/run_quality_idle_reasons.json.
REAL_IDLE_TOKENS = ("no_pending_events", "all_already_settled", "nothing_due", "no_new_input", "no_new_events",
                    "below_trigger", "market_closed", "no pending proposal needed an alert this run")


@pytest.mark.parametrize("token", REAL_IDLE_TOKENS)
def test_a_reviewed_no_work_reason_grades_idle(token):
    assert token in Q.idle_reasons(), f"{token} must be a reviewed idle token (config, not code)"
    q = _grade(receipt(produced_count=0, empty_reason=token))
    assert (q["grade"], q["sub"]) == ("IDLE", token), q["reasons"]
    assert "nothing to do" in q["headline"] and q["reasons"], q["headline"]


def test_idle_is_not_good_so_it_is_never_green():
    q = _grade(receipt(produced_count=0, empty_reason="below_trigger"))
    assert q["grade"] == "IDLE"
    d = J.display_status({**job_row(), "quality": q})
    assert d["green"] is False and d["label"] == "Ran on time, result nothing to do"


def test_a_zero_without_a_reviewed_reason_stays_empty():
    # dependency_unavailable is a real receipt reason and is deliberately NOT idle: the work did not happen
    # because something it needed was missing — that is a defect, not a correct zero.
    assert "dependency_unavailable" not in Q.idle_reasons()
    q = _grade(receipt(produced_count=0, empty_reason="dependency_unavailable"))
    assert q["grade"] == "EMPTY", q["reasons"]


def test_an_idle_reason_in_the_summary_counts_too():
    q = _grade(receipt(produced_count=0, summary={"empty_reason": "no_pending_events"}))
    assert (q["grade"], q["sub"]) == ("IDLE", "no_pending_events"), q["reasons"]


def test_an_idle_run_that_touched_no_output_file_is_still_idle_not_empty_not_written():
    q = _grade(receipt(produced_count=0, empty_reason="all_already_settled"), output_at=None)
    assert q["grade"] == "IDLE", q["reasons"]
    assert q["checks"]["output_written"]["result"] == "pass"


def test_an_idle_run_with_a_stale_input_is_still_degraded():
    ev = {"receipt": receipt(produced_count=0, empty_reason="no_new_input"), "receipt_path": None,
          "output_at": FINISH, "ledger": [], "history": [], "contract": None,
          "freshness": ["synthetic feed is 3 d old (limit 1 d)"], "freshness_known": True,
          "plausibility": [], "plausibility_known": True}
    q = Q.grade(ROW, LANE, ev, now=NOW)
    assert q["grade"] == "DEGRADED" and "synthetic feed" in q["headline"]


# ── AC-3: one word, one meaning — the row status is subject_degraded, DEGRADED is the quality grade ─────────────

def test_the_row_status_degraded_is_renamed_subject_degraded():
    assert "subject_degraded" in J.STATUS_FILTERS
    assert "degraded" not in J.STATUS_FILTERS, "the row status must not reuse the quality grade's word"
    row = job_row(status="subject_degraded", status_reason="Last run's receipt reports a degraded subject")
    assert J.STATUS_FILTERS["subject_degraded"](row)
    d = J.display_status(row)
    assert d["green"] is False and d["tone"] == "warning"
    assert d["label"] == "Last run reports degraded"


def test_the_quality_grade_and_the_row_status_say_different_words():
    # quality DEGRADED is a grade of the OUTPUT; it is asked for with ?quality=DEGRADED, never ?status=degraded.
    assert "DEGRADED" in J.QUALITY_GRADES and "IDLE" in J.QUALITY_GRADES
    assert "degraded" not in J.STATUS_FILTERS and "subject_degraded" not in J.QUALITY_GRADES


# ── the summary: display_counts reconcile with the rows, and the filters partition them ─────────────────────────

def _wire(rows):
    return J.annotate_display({"rows": rows, "summary": {"jobs": len(rows), "active": len(rows)}})


def test_display_counts_reconcile_with_the_rows():
    rows = [
        job_row(grade="GOOD", lane_id="a"),                       # green
        job_row(grade="UNPROVEN", lane_id="b"),                   # amber
        job_row(grade="IDLE", lane_id="c"),                       # amber
        job_row(grade=None, lane_id="d"),                         # amber (unmeasured is not good)
        job_row(status="failed", grade="FAILED", lane_id="e"),    # other
        job_row(status="subject_degraded", grade="DEGRADED", lane_id="f"),  # other
        job_row(status="missed", grade="GOOD", lane_id="g"),      # other
    ]
    out = _wire(rows)
    counts = out["summary"]["display_counts"]
    assert counts == {"green": 1, "amber": 3, "other": 3}
    assert counts["green"] + counts["amber"] + counts["other"] == len(rows)
    assert sum(1 for r in rows if r["display"]["green"]) == counts["green"]


def test_the_green_and_amber_filters_partition_the_ok_rows():
    rows = [job_row(grade="GOOD", lane_id="a"), job_row(grade="EMPTY", lane_id="b"),
            job_row(grade="IDLE", lane_id="c"), job_row(status="failed", lane_id="d")]
    _wire(rows)
    assert [r["lane_id"] for r in rows if J.STATUS_FILTERS["green"](r)] == ["a"]
    assert [r["lane_id"] for r in rows if J.STATUS_FILTERS["amber"](r)] == ["b", "c"]
    ok_rows = [r for r in rows if r["status"] == "ok"]
    assert len(ok_rows) == 3  # every ok row is exactly one of green / amber
    assert sum(1 for r in rows if J.STATUS_FILTERS["green"](r) or J.STATUS_FILTERS["amber"](r)) == len(ok_rows)


def test_the_list_projection_carries_the_display_decision():
    row = _wire([job_row(grade="UNPROVEN")])["rows"][0]
    listed = J._list_row(row)
    assert listed["display"]["green"] is False and listed["display"]["schema"] == "JobDisplayStatus@v1"
    assert listed["display"]["label"] == "Ran on time, result unproven"
