"""investment-costs: a failing reconciliation, and the count a passing one still needs (2026-11-07).

Ops › Quality: **FAILED — "Last live run 6 h ago failed (exit 0) (its receipt says status failed); 11
failures in a row"**. The receipt (`data/runtime/investment-costs_last.json`, 2026-11-06T22:05:01Z)
says `status failed`, `exit 0`, `reconciliation_ok false`, `ingested_new 8`, `accrued_rows 0`,
`missing_rate_count 26`. The log's failing check is `ledger_fees_vs_normalized`: raw ledger 115.99,
normalized events 116.77 — a difference of exactly $0.78, the six charges whose trade row was dropped
by the 2026-10-28 re-import. `f463a8c6d` (merged into the integration branch, served by 79e893b8a,
after that run) adds the named-orphan term to the comparison, which clears the failure.

Clearing it is not enough to reach GOOD. The lane's only output signal is its own `ok_at`, and the
receipt stated no count `run_quality.item_count` reads — `summary.accrued_rows` is 0 on a normal day
because 26 holdings lack an expense rate — so the next run would grade UNPROVEN. The receipt now
states `produced_count` = rows written into `investment_cost_events` (ingested + accrued), and
`empty_reason: no_new_events` when that is 0.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = "investment-costs"


def _registry_row() -> dict:
    doc = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
    lanes = doc["lanes"] if isinstance(doc, dict) else doc
    rows = lanes.values() if isinstance(lanes, dict) else lanes
    return next(row for row in rows if row.get("lane_id") == LANE)


def _contract() -> dict:
    doc = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))
    return next(c for c in doc["contracts"] if c.get("id") == LANE)


def _receipt(*, ok: bool, produced: int | None, empty_reason: str | None = None) -> dict:
    """The 2026-11-06 run's shape, with the fields the next run writes."""
    started = "2026-11-06T22:05:01.409253+00:00"
    finished = "2026-11-06T22:05:01.556559+00:00"
    doc = {
        "schema": "LaneRunReceipt@v2" if produced is not None else "LaneRunReceipt@v1",
        "lane_id": LANE,
        "script": "investment-costs",
        "mode": "live",
        "status": "ok" if ok else "failed",
        "exit": 0,
        "started_at": started,
        "finished_at": finished,
        "ok_at": finished if ok else None,
        "summary": {
            "ingested_new": 8,
            "accrued_rows": 0,
            "missing_rate_count": 26,
            "stale_rate_count": 0,
            "reconciliation_checks": 6,
            "reconciliation_ok": ok,
        },
        "consecutive_failures": 0 if ok else 11,
    }
    if produced is not None:
        doc["produced_count"] = produced
    if empty_reason:
        doc["empty_reason"] = empty_reason
    return doc


def _grade(receipt: dict) -> dict:
    from scripts.lib import run_quality as RQ

    row = {
        "lane_id": LANE,
        "status": "ok",
        "runs": [
            {
                "result": "succeeded" if receipt["status"] == "ok" else "failed",
                "mode": "live",
                "started_at": receipt["started_at"],
                "source": "lane receipt",
                "finished_at": receipt["finished_at"],
                "duration_s": 0.147,
            }
        ],
    }
    evidence = {
        "contract": _contract(),
        "receipt": receipt,
        "receipt_path": "data/runtime/investment-costs_last.json",
        "output_at": receipt["finished_at"],
        "history": [],
        "freshness": [],
        "freshness_known": True,
        "plausibility": [],
        "plausibility_known": True,
    }
    return RQ.grade(row, _registry_row(), evidence, now=datetime(2026, 11, 7, 4, 30, tzinfo=timezone.utc))


# the reconciliation arithmetic (the named-orphan term) is pinned by
# tests/test_investment_costs_reconciliation_20261107.py, merged with f463a8c6d.

# --- the count the receipt understates ------------------------------------------------------------------


def test_produced_rows_counts_every_row_the_run_wrote():
    from scripts.investment_costs import produced_rows

    assert produced_rows({"ingested_new": 8}, {"accrued_rows": 0}) == 8  # the 2026-11-06 run
    assert produced_rows({"ingested_new": 0}, {"accrued_rows": 26}) == 26
    assert produced_rows({"ingested_new": 3}, {"accrued_rows": 4}) == 7


def test_produced_rows_never_invents_a_count_from_a_broken_result():
    from scripts.investment_costs import produced_rows

    assert produced_rows({}, {"error": "holdings unavailable: missing"}) == 0
    assert produced_rows({"ingested_new": None}, {"accrued_rows": None}) == 0
    assert produced_rows({"ingested_new": True}, {"accrued_rows": -5}) == 0


# --- the grades -----------------------------------------------------------------------------------------


def test_the_reported_receipt_grades_failed_exactly_as_the_surface_shows():
    """The fixture is the served receipt's own fields (2026-11-06T22:05:01Z), copied verbatim."""
    graded = _grade(_receipt(ok=False, produced=None))
    assert graded["grade"] == "FAILED"
    assert "11 failures in a row" in graded["headline"]


def test_a_passing_run_that_states_its_count_grades_good():
    graded = _grade(_receipt(ok=True, produced=8))
    assert graded["grade"] == "GOOD", graded["headline"]
    assert graded["count"]["value"] == 8 and graded["count"]["key"] == "produced_count"


def test_a_passing_run_without_a_count_would_only_be_unproven():
    graded = _grade(_receipt(ok=True, produced=None))
    assert graded["grade"] == "UNPROVEN" and graded["sub"] == "output_unverifiable"


def test_a_run_that_wrote_nothing_is_a_stated_idle_run_not_an_empty_failure():
    graded = _grade(_receipt(ok=True, produced=0, empty_reason="no_new_events"))
    assert graded["grade"] == "GOOD" and graded["sub"] == "idle", graded["headline"]
    allowed = _contract()["expected_output"]["empty_allowed_reasons"]
    assert "no_new_events" in allowed, "the n8n executor must honour the same idle reason"
