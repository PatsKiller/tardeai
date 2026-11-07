"""ANCHOR: NEWS_TO_CATALYST_GATE_EXCLUSIONS_20261107 — a gate refusal is not a skip.

WORK-QUEUE item 26 (2026-11-07): a normal full `news-to-catalyst` run — 500 candidates, 420 of them refused
by the identity gates because their "symbol" was a research-directive slug, 80 created — graded DEGRADED
with "skipped 420 items, more than it produced (80)". The run was healthy: 420 of its candidates were
never eligible, so counting them as skips the run chose compared a population against itself.

The producer now reports them under ``excluded_reasons`` (and subtracts them from ``attempted_count``);
the receipt writer carries that field; the grader reads it as a stated structural exclusion, never as a
skip. Synthetic counts and lanes only — no real lane, score or store.
"""
from __future__ import annotations

import importlib

import pytest

from scripts.lib import lane_last_receipt as R
from scripts.lib import run_quality as Q

NOW_RECEIPT = None  # receipts below are graded with the same helper the lane tests use


def _n2c():
    """The lane script (conftest puts ``scripts/`` on the path)."""
    return importlib.import_module("news_to_catalyst")


# ── the producer states two different accounts ──────────────────────────────────────────────────────────────────

def test_gate_refusals_are_excluded_not_skipped():
    out = _n2c().lane_output({
        "candidates": 500, "attempted": 80, "created": 80,
        "skipped": {"already_present": 0},
        "excluded": {"research_directive_slug": 420, "not_in_ticker_universe": 0},
    })
    assert out["excluded_reasons"] == {"research_directive_slug": 420}
    assert out["skipped_reasons"] == {}
    assert out["produced_count"] == 80
    assert out["attempted_count"] == 80          # eligible, not the query's 500
    assert out["empty_reason"] is None


def test_a_duplicate_is_still_a_skip_kept_separate():
    """"Keep chosen skips": a candidate that already had its row is the lane's own account, not an exclusion."""
    out = _n2c().lane_output({
        "candidates": 12, "attempted": 12, "created": 3,
        "skipped": {"already_present": 9}, "excluded": {},
    })
    assert out["skipped_reasons"] == {"already_present": 9}
    assert out["excluded_reasons"] == {}
    assert out["empty_reason"] is None          # it produced


def test_a_run_of_only_gate_refusals_names_its_empty_kind():
    out = _n2c().lane_output({
        "candidates": 40, "attempted": 0, "created": 0,
        "skipped": {}, "excluded": {"research_directive_slug": 40},
    })
    assert (out["produced_count"], out["attempted_count"]) == (0, 0)
    assert out["empty_reason"] == "no_eligible_candidates"


# ── the receipt writer must not drop the field ──────────────────────────────────────────────────────────────────

def test_receipt_writer_carries_excluded_reasons():
    """``output_fields`` whitelists keys; a field it does not know is silently dropped (this test is why)."""
    fields = R.output_fields({
        "produced_count": 80, "attempted_count": 80,
        "skipped_reasons": {}, "excluded_reasons": {"research_directive_slug": 420},
    })
    assert fields["excluded_reasons"] == {"research_directive_slug": 420}
    assert "excluded_reasons" in R.OUTPUT_FIELDS


def test_receipt_writer_counts_are_ints_and_drop_junk():
    fields = R.output_fields({"excluded_reasons": {"a": "7", "b": None, "c": -2}})
    assert fields["excluded_reasons"] == {"a": 7, "c": 0}


# ── the grader ────────────────────────────────────────────────────────────────────────────────────────────────

def test_structural_exclusions_never_grade_a_run_degraded():
    rc = {"started_at": "2026-11-07T14:00:00Z", "finished_at": "2026-11-07T14:01:00Z", "status": "ok",
          "produced_count": 80, "attempted_count": 80,
          "skipped_reasons": {}, "excluded_reasons": {"research_directive_slug": 420}}
    flags = Q.receipt_flags(rc, count=80)
    assert flags == [], flags
    notes = Q.excluded_notes(rc)
    assert notes and "420" in notes[0] and "never eligible" in notes[0]
    assert "500" in notes[0]                     # 80 attempted + 420 excluded


def test_the_old_shape_is_still_flagged():
    """A receipt that reports gate refusals as skips is the defect, and stays DEGRADED until its producer is fixed."""
    rc = {"started_at": "2026-11-07T14:00:00Z", "finished_at": "2026-11-07T14:01:00Z", "status": "ok",
          "produced_count": 80, "attempted_count": 500,
          "skipped_reasons": {"research_directive_slug": 420}}
    flags = Q.receipt_flags(rc, count=80)
    assert any("skipped 420" in f for f in flags), flags


def test_no_exclusions_means_no_note():
    assert Q.excluded_notes({"excluded_reasons": {}}) == []
    assert Q.excluded_notes({"excluded_reasons": {"x": 0}}) == []
    assert Q.excluded_notes(None) == []


# ── end to end: produced 80 of 80 attempted is GOOD ─────────────────────────────────────────────────────────────

def _grade(receipt_doc):
    from datetime import datetime, timedelta, timezone
    from scripts.lib import run_quality as Q2
    now = datetime(2026, 11, 7, 15, 7, tzinfo=timezone.utc)
    start = now - timedelta(minutes=30)
    z = lambda dt: dt.isoformat().replace("+00:00", "Z")  # noqa: E731
    lane = {"lane_id": "synthetic-lane", "state": "ACTIVE",
            "output_signal": {"kind": "file_mtime", "path": "data/runtime/synthetic-lane_out.json"},
            "scheduler": {"kind": "n8n", "stage": "live"}, "dispatch": {"mode": "live"}}
    run = {"mode": "live", "result": "succeeded", "started_at": z(start),
           "finished_at": z(start + timedelta(seconds=60)), "duration_s": 60, "run_id": "r1",
           "exit_code": 0, "reason": None, "source": "n8n run ledger"}
    row = {"lane_id": "synthetic-lane", "state": "ACTIVE", "status": "ok", "runs": [run], "last_run": run}
    diag = {"receipt": receipt_doc, "receipt_path": None, "output_at": now - timedelta(minutes=29), "ledger": [],
            "history": [], "contract": None, "freshness": [], "freshness_known": True, "plausibility": [],
            "plausibility_known": True}
    return Q2.grade(row, lane, diag, now=now)


def test_a_full_run_with_420_gate_refusals_grades_good():
    rc = {"started_at": "2026-11-07T14:37:00Z", "finished_at": "2026-11-07T14:38:00Z", "status": "ok",
          "produced_count": 80, "attempted_count": 80,
          "skipped_reasons": {}, "excluded_reasons": {"research_directive_slug": 420}}
    q = _grade(rc)
    assert q["grade"] == "GOOD", q
    assert q["checks"]["receipt_flags"] == {"result": "pass", "value": 0}
    assert "never eligible, not skips" in q["checks"]["excluded_candidates"]["detail"]
