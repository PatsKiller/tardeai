"""HOLDINGS_WRITER_ORDERING_20261103 — the writer that changes rows reconciles every total it invalidates.

2026-11-03 18:37:12Z: `schwab_position_sync` added the PFE row and moved the rollover cash row by
-30,450.00, and the gate reconciled only `portfolio_totals.total_value`. The store then read
total_cash 847,552.75 against cash rows summing to 817,102.75, and
`account_summaries.schwab_rollover_ira.cash` stayed at 807,840.61 against a row of 777,390.61.
Two fixes already exist: #2554 reconciles `portfolio_totals.total_cash` at the same gate. This file
pins the remaining half — the per-account cash summary, run provenance (`last_writer`) and the stale
`portfolio_totals.note` cleared as a proper write — and proves the whole thing END TO END through
`protected_holdings_write`, not just through the helper.
"""

from __future__ import annotations

import json

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from schwab_position_sync import protected_holdings_write, reconcile_totals  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_side_effects(monkeypatch):
    """No DB receipt and no alert: this file may share a CI shard with a test that snapshots the tree.

    `_record` would reach db_adapter (which falls back to a local JSON store when the driver/DSN is
    unavailable) and `_alert` would attempt a notification. Neither is part of what these tests
    assert, and either could write inside the checkout while another gate is proving read-only
    behaviour.
    """
    import schwab_position_sync as sps

    monkeypatch.setattr(sps, "_record", lambda *a, **k: None)
    monkeypatch.setattr(sps, "_alert", lambda *a, **k: None)

STALE_NOTE = "rebuilt from positions_current run 638; day change not carried"


def _doc(
    *,
    rollover_cash_row=777390.61,
    summary_cash=807840.61,
    declared_cash=847552.75,
    day_change=-1965.82,
    note=STALE_NOTE,
    summary_with_cash=True,
):
    holdings = [
        {"symbol": "CASH", "account": "alpaca_taxable_live", "is_cash": True, "market_value": 5000.0},
        {"symbol": "CASH", "account": "moomoo_taxable_live", "is_cash": True, "market_value": 500.0},
        {"symbol": "CASH", "account": "schwab_taxable", "is_cash": True, "market_value": 33583.83},
        {"symbol": "CASH", "account": "schwab_roth", "is_cash": True, "market_value": 628.31},
        {"symbol": "CASH", "account": "schwab_rollover_ira", "is_cash": True, "market_value": rollover_cash_row},
        {"symbol": "PFE", "account": "schwab_rollover_ira", "shares": 1000.0, "market_value": 30360.0},
        {"symbol": "AAA", "account": "schwab_taxable", "shares": 10.0, "market_value": 1200.0},
    ]
    totals = {
        "total_value": sum(r["market_value"] for r in holdings),
        "total_cash": declared_cash,
        "day_change": day_change,
    }
    if note is not None:
        totals["note"] = note
    summaries = {
        "alpaca_taxable_live": {"cash": 5000.0, "positions": 1},
        "moomoo_taxable_live": {"cash": 500.0, "positions": 1},
        "schwab_taxable": {"cash": 33583.83, "positions": 2},
        "schwab_roth": {"cash": 628.31, "positions": 1},
        "schwab_rollover_ira": {"positions": 1},
    }
    if summary_with_cash:
        summaries["schwab_rollover_ira"]["cash"] = summary_cash
    return {"holdings": holdings, "portfolio_totals": totals, "account_summaries": summaries}


def test_the_rollover_cash_summary_is_reconciled_from_its_own_rows():
    doc = _doc()
    c = reconcile_totals(doc, source="schwab_position_sync")
    assert doc["account_summaries"]["schwab_rollover_ira"]["cash"] == 777390.61
    assert doc["account_summaries"]["schwab_rollover_ira"]["cash_source"] == "position_rows"
    assert c["summaries_cash"] == [
        {"account": "schwab_rollover_ira", "declared": 807840.61, "summed": 777390.61, "delta": -30450.0}
    ]


def test_a_summary_that_carries_no_cash_is_not_invented():
    doc = _doc(summary_with_cash=False)
    reconcile_totals(doc, source="schwab_position_sync")
    assert "cash" not in doc["account_summaries"]["schwab_rollover_ira"]


def test_a_reconciled_summary_is_left_alone():
    doc = _doc(summary_cash=777390.61, declared_cash=817102.75, note=None)
    c = reconcile_totals(doc, source="schwab_position_sync")
    assert c is None
    assert "cash_reconciled_at" not in doc["account_summaries"]["schwab_rollover_ira"]


def test_the_note_is_cleared_only_when_its_claim_is_false():
    doc = _doc()
    c = reconcile_totals(doc, source="schwab_position_sync")
    assert "note" not in doc["portfolio_totals"]
    assert c["note_cleared"] == STALE_NOTE
    # ... and it is KEPT while day_change really is not carried.
    doc2 = _doc(day_change=None)
    reconcile_totals(doc2, source="schwab_position_sync")
    assert doc2["portfolio_totals"]["note"] == STALE_NOTE


def test_every_gate_write_records_last_writer_and_does_not_touch_rows():
    doc = _doc()
    rows_before = json.loads(json.dumps(doc["holdings"]))
    reconcile_totals(doc, source="schwab_position_sync")
    lw = doc["last_writer"]
    assert lw["source"] == "schwab_position_sync" and lw["at"]
    assert lw["summaries_cash_reconciled"] == ["schwab_rollover_ira"]
    assert lw["note_cleared"] == STALE_NOTE
    assert doc["holdings"] == rows_before, "a totals reconciliation must never rewrite a row"


def test_a_clean_write_still_records_provenance():
    doc = _doc(summary_cash=777390.61, declared_cash=817102.75, note=None)
    reconcile_totals(doc, source="portfolio_repricer")
    assert doc["last_writer"] == {
        "source": "portfolio_repricer",
        "at": doc["last_writer"]["at"],
        "total_value_reconciled": False,
        "total_cash_reconciled": False,
        "summaries_cash_reconciled": [],
        "note_cleared": None,
    }


def test_the_writer_path_leaves_the_store_reconciled_end_to_end(tmp_path):
    """Through the real gate: the file that lands on disk reconciles, and PFE is untouched."""
    target = tmp_path / "holdings.json"
    stale = _doc()
    target.write_text(json.dumps(stale), encoding="utf-8")

    new = _doc()
    new["portfolio_totals"]["total_value"] = 1  # force a value correction too
    res = protected_holdings_write(new, source="writer_ordering_test", account_key="test", target_path=target)

    assert res.get("wrote") is True, res
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    rows = on_disk["holdings"]
    assert round(sum(r["market_value"] for r in rows), 2) == on_disk["portfolio_totals"]["total_value"]
    assert on_disk["portfolio_totals"]["total_cash"] == round(
        sum(r["market_value"] for r in rows if r.get("is_cash")), 2
    )
    assert on_disk["account_summaries"]["schwab_rollover_ira"]["cash"] == 777390.61
    assert on_disk["last_writer"]["source"] == "writer_ordering_test"
    assert "note" not in on_disk["portfolio_totals"]
    pfe = [r for r in rows if r["symbol"] == "PFE"]
    assert pfe == [{"symbol": "PFE", "account": "schwab_rollover_ira", "shares": 1000.0, "market_value": 30360.0}], (
        "the real position row must not move"
    )
