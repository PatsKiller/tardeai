"""DATA TRUTH P0 defect 4 (2026-11-07): the run-quality grader must not grade GOOD a run that produced nothing.

Three cases from ``DATA-TRUTH-AUDIT-20261107.md`` §Defects 4, each with the receipt shape captured from the live
run that produced it (values copied; no lane, store or file is read):

* ``topic-research-synthesizer`` — a ``FamilySlotRun@v1`` receipt whose ``results`` is one record per MODE
  (``{"mode": "synth", "rc": 0, "log": …}``). Counting the list said "produced 1" while the log for the same run
  said ``candidates: 0, synthesized: 0``.
* ``hermes-watchlist-scorer`` — a receipt whose resolved count is 629 while ``written`` is 0 and
  ``skipped_unchanged`` is 629: it scored nothing, it re-looked at everything.
* ``portfolio-maintenance-daily`` — ``overall_status: degraded`` with a ``FAILED(rc=1)`` step and the rest
  ``EXCLUDED_NOT_RUN``. A failed step is the run's outcome, not a partial.

Hermetic: synthetic receipts only; the repo is PUBLIC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib import run_quality as Q

NOW = datetime(2026, 11, 7, 4, 30, tzinfo=timezone.utc)


def z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def lane(lane_id="synthetic-lane"):
    return {"lane_id": lane_id, "state": "ACTIVE",
            "output_signal": {"kind": "json_key", "path": "data/runtime/synthetic_last.json", "key": "ok_at"},
            "scheduler": {"kind": "n8n"}, "dispatch": {"mode": "live"}}


def row(ago_min=10, *, run_id="r1"):
    start = NOW - timedelta(minutes=ago_min)
    return {"lane_id": "synthetic-lane", "state": "ACTIVE", "status": "ok",
            "runs": [{"mode": "live", "result": "succeeded", "started_at": z(start),
                      "finished_at": z(start + timedelta(seconds=5)), "duration_s": 5, "run_id": run_id,
                      "exit_code": 0, "source": "n8n run ledger"}],
            "last_run": None}


def receipt(ago_min=10, **extra):
    start = NOW - timedelta(minutes=ago_min)
    done = start + timedelta(seconds=5)
    return {"started_at": z(start), "finished_at": z(done), "status": "ok", "ok_at": z(done), **extra}


def ev(rec):
    return {"receipt": rec, "receipt_path": "data/runtime/synthetic_last.json",
            "output_at": NOW - timedelta(minutes=9), "ledger": [], "history": [], "contract": None,
            "freshness": [], "freshness_known": True, "plausibility": [], "plausibility_known": True}


def g(rec, *, r=None, ln=None):
    return Q.grade(r or row(), ln or lane(), ev(rec), now=NOW)


# ── case 1: a per-mode execution record is not a produced item ───────────────────────────────────────────────
FAMILY_SLOT = {"schema": "FamilySlotRun@v1", "slot": "2026-11-06T23:20",
               "results": [{"mode": "synth", "rc": 0, "log": "logs/topic_research_synth.log",
                            "gate_prediction": "allow"}]}


def test_a_mode_record_is_not_a_produced_item():
    assert Q.item_count({"summary": FAMILY_SLOT}) == (None, None)


def test_a_receipt_with_only_mode_records_is_never_good():
    out = g(receipt(summary=FAMILY_SLOT))
    assert out["grade"] != "GOOD", out["headline"]
    assert out["count"]["value"] is None, "no item count can be read from a list of mode records"


def test_a_list_of_real_items_still_counts():
    produced = {"summary": {"results": [{"symbol": "AAA", "brief_id": 1}, {"symbol": "BBB", "brief_id": 2}]}}
    assert Q.item_count(produced) == (2, "summary.results[]")


# ── case 2: a count that was never written is not output ────────────────────────────────────────────────────
def test_scoring_629_unchanged_and_writing_none_is_empty_not_good():
    rec = receipt(produced_count=629,
                  summary={"items": 629, "scored": 629, "written": 0, "skipped_unchanged": 629, "errored": 0,
                           "mode": "frozen-ranks"})
    out = g(rec)
    assert out["grade"] == "EMPTY", out["headline"]
    assert out["count"]["value"] == 0 and out["count"]["key"] == "summary.written"


def test_a_written_count_is_still_the_runs_output():
    rec = receipt(summary={"scored": 9, "written": 9, "skipped_unchanged": 0})
    out = g(rec)
    assert out["count"]["value"] == 9 and out["grade"] != "EMPTY"


# ── case 3: a failed step is the run's outcome ──────────────────────────────────────────────────────────────
MAINTENANCE = {"pipeline": "portfolio-maintenance", "cadence": "daily", "run_ts_utc": "2026-11-06T12:30:09Z",
               "dry_run": False, "overall_status": "degraded",
               "steps": [{"name": "portfolio_daily_report", "status": "FAILED(rc=1)"},
                         {"name": "price_cache", "status": "EXCLUDED_NOT_RUN"},
                         {"name": "db_retention", "status": "EXCLUDED_NOT_RUN"}]}


def test_a_failed_step_grades_failed_not_degraded():
    out = g(receipt(overall_status="degraded", steps=MAINTENANCE["steps"]))
    assert out["grade"] == "FAILED", (out["grade"], out["headline"])
    assert "portfolio_daily_report" in " ".join(out["reasons"])


def test_an_excluded_or_ok_step_does_not_fail_the_run():
    out = g(receipt(overall_status="ok", steps=[{"name": "price_cache", "status": "OK", "rc": 0},
                                                {"name": "db_retention", "status": "EXCLUDED_NOT_RUN"}]))
    assert out["grade"] != "FAILED", out["headline"]


def test_a_bare_failed_step_code_fails_the_run():
    out = g(receipt(overall_status="ok", steps=[{"name": "portfolio_daily_report", "rc": 1}]))
    assert out["grade"] == "FAILED", (out["grade"], out["headline"])


def test_a_step_on_a_declared_verdict_exit_is_not_a_failed_step():
    rec = receipt(success_exit_codes=[1],
                  steps=[{"name": "source_litmus_vs_yahoo", "status": "ok", "rc": 1}])
    assert Q.failed_step(rec) is None
    assert g(rec)["grade"] != "FAILED"
