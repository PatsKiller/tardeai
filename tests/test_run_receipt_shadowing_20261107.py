"""ANCHOR: RUN_RECEIPT_SHADOWING_20261107 — a store that says *when* may not speak for a run that says *what*.

QUALITY ROUND 2, WORK-QUEUE item 4 (portfolio-repricer). Every cron fire writes a real run receipt —
``data/runtime/portfolio-repricer_last.json``, ``schema: LaneRunReceipt@v2``, ``status: ok``, ``exit: 0``,
``started_at``/``finished_at``, ``produced_count: 34`` — yet the lane row read
``ok_unverified: "Last run's receipt does not state success"`` and the card graded
``UNPROVEN / no_run_record`` ("the file states a time but no run start, status or exit code").

The cause is candidate order, not the lane. portfolio-repricer's declared output signal is
``data/portfolios/state/holdings.json`` — a business store several writers touch — and
``run_quality.receipt_candidates`` puts a declared ``*.json`` output *first*. ``read_receipt`` accepts it because
it carries ``as_of``, so the lane's own receipt one candidate later is never read; ``receipt_run`` then builds a
"run" whose start is the store's ``as_of`` and whose result is ``unknown``. Being within ``SAME_RUN`` of the real
receipt, that pseudo-run also suppressed the receipt in ``lane_history``.

This file pins the rule jobs_history must keep: a document that names no run start or finish is not a run receipt.
A receipt that names its run wins; the store keeps serving as the lane's OUTPUT time (freshness), which is what it
is. And a lane with only a store and no receipt at all keeps the evidence it has today — the fix must not strip the
last-run time from the ~130 lanes whose only receipt-shaped document is a state file.

Synthetic fixtures only: temp trees, hand-written JSON, no production store, no database, no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib import jobs_history as J

NOW = datetime(2026, 11, 7, 4, 45, tzinfo=timezone.utc)
WEEKDAY = lambda d: d.weekday() < 5  # noqa: E731
LANE = "portfolio-repricer"

#: The shape of the incident's store: an output document with a bare ``as_of`` and nothing about a run.
STORE = {"schema": "holdings@v1", "as_of": "2026-11-07T04:30:05.911837Z",
         "holdings": [{"symbol": "NVDA"}], "gaps": ["fund look-through unavailable: etf_holdings_snapshot is not applied"]}

#: The lane's own receipt, written 3 s earlier than the store's as_of (the store is written BY that run).
RECEIPT = {"schema": "LaneRunReceipt@v2", "lane_id": LANE, "script": "scripts/portfolio_repricer.py",
           "mode": "live", "status": "ok", "exit": 0,
           "started_at": "2026-11-07T04:30:02.187221+00:00", "finished_at": "2026-11-07T04:30:10.748605+00:00",
           "ok_at": "2026-11-07T04:30:10.748605+00:00", "produced_count": 34, "attempted_count": 34,
           "summary": {"holdings_updated": 25, "holdings": 34}}


def _lane(lane_id: str = LANE) -> dict:
    return {"lane_id": lane_id, "state": "ACTIVE",
            "output_signal": {"kind": "file_mtime", "path": "data/portfolios/state/holdings.json"},
            "scheduler": {"kind": "cron", "expression": "*/15 * * * 1-5", "timezone": "America/New_York"}}


def _tree(tmp_path: Path, *, lane_id: str = LANE, store: dict | None = STORE, receipt: dict | None = RECEIPT) -> Path:
    root = tmp_path / "state"
    (root / "data/portfolios/state").mkdir(parents=True)
    (root / "data/runtime").mkdir(parents=True)
    (root / "logs").mkdir(parents=True)
    if store is not None:
        (root / "data/portfolios/state/holdings.json").write_text(json.dumps(store))
    if receipt is not None:
        (root / f"data/runtime/{lane_id}_last.json").write_text(json.dumps(receipt))
    return root


def _row(out, lane_id=LANE):
    return next(r for r in out["rows"] if r["lane_id"] == lane_id)


def _build(registry_lanes, **inputs):
    inputs.setdefault("ledger_since", NOW - timedelta(days=10))
    inputs.setdefault("journal_since", NOW - timedelta(days=10))
    return J.build({"lanes": registry_lanes}, inputs, now=NOW, trading_day=WEEKDAY)


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_store_that_names_no_run_is_not_a_run_receipt():
    assert J.receipt_run(STORE, None) is not None        # today's parser still builds a "run" from as_of alone
    assert J.names_a_run(J.receipt_run(STORE, None)) is False
    assert J.names_a_run(J.receipt_run(RECEIPT, None)) is True


def test_the_receipt_that_names_its_run_wins_over_the_store(tmp_path):
    root = _tree(tmp_path)
    doc, rel = J.receipt_naming_a_run(_lane(), root)
    assert rel == f"data/runtime/{LANE}_last.json"
    assert doc["status"] == "ok" and doc["produced_count"] == 34


def test_the_lane_receipt_is_read_even_though_the_store_is_listed_first(tmp_path):
    root = _tree(tmp_path)
    receipts = J.read_lane_receipts({"lanes": [_lane()]}, root)
    assert receipts[LANE]["result"] == "succeeded"
    assert receipts[LANE]["source"] == "lane receipt"
    assert receipts[LANE]["started_at"].startswith("2026-11-07T04:30:02")


def test_the_store_still_serves_as_the_output_time(tmp_path):
    root = _tree(tmp_path)
    _receipts, outputs = J.read_receipts({"lanes": [_lane()]}, root)
    assert LANE in outputs                      # freshness evidence is untouched by this fix


# ── the row the operator sees ─────────────────────────────────────────────────────────────────────────────────────

def test_a_bare_as_of_does_not_mask_the_run_the_lane_receipt_names():
    pseudo = J.receipt_run(STORE, None)
    real = J.receipt_run(RECEIPT, None)
    real["source"] = "lane receipt"
    out = _build([_lane()], receipts={LANE: pseudo}, lane_receipts={LANE: real},
                 output_times={LANE: NOW - timedelta(minutes=12)})
    row = _row(out)
    assert row["last_run"]["result"] == "succeeded", row["last_run"]
    assert row["last_run"]["source"] == "lane receipt"
    assert row["status"] == "ok", row["status_reason"]


def test_a_lane_with_only_a_store_and_no_receipt_keeps_its_last_run_time():
    """The ~130 lanes whose only receipt-shaped document is a state file must not lose their evidence."""
    pseudo = J.receipt_run(STORE, None)
    out = _build([_lane("state-only-lane")], receipts={"state-only-lane": pseudo},
                 output_times={"state-only-lane": NOW - timedelta(minutes=12)})
    row = _row(out, "state-only-lane")
    assert row["last_run"]["result"] == "unknown"      # unchanged: a time is still not a result
    assert row["last_run"]["source"] == "run receipt (last run only)"
    # its as_of still places the slot, which is all this document ever proved
    assert any(s["started_at"] == "2026-11-07T04:30:05.911837Z" and s["status"] == "ran" for s in row["slots"])
