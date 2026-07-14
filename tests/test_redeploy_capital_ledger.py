#!/usr/bin/env python3
"""Account capital ledger — OVR-P0-CAPITAL-POOL-OVERCLAIM (pure-function tests).

Proves that open events in one account reserve capital sequentially instead of
each independently claiming the same visible-cash dollars. No DB required.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _ledger_mod():
    spec = importlib.util.spec_from_file_location(
        "redeploy_capital_book", ROOT / "scripts/lib/redeploy_capital_book.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _row(event_id, account="schwab_rollover_ira", remaining=0.0, deployed=0.0,
         locked_plan_id=None, operator_status=None, completion_status="open",
         sold_at="2026-07-01", warnings=None):
    return {
        "event_id": event_id,
        "account": account,
        "remaining_usd": remaining,
        "deployed_usd": deployed,
        "locked_plan_id": locked_plan_id,
        "operator_status": operator_status,
        "completion_status": completion_status,
        "sold_at": sold_at,
        "warnings": warnings if warnings is not None else [],
    }


def test_same_account_events_allocate_sequentially():
    """Two events that each fit alone must share one pool, oldest first."""
    cb = _ledger_mod()
    rows = [
        _row(114, remaining=17541.0, sold_at="2026-07-02"),
        _row(124, remaining=17541.0, sold_at="2026-07-08"),
    ]
    # Pool covers exactly one claim plus a bit — the second must wait.
    acct_map = cb.apply_capital_ledger(rows, {"schwab_rollover_ira": 20000.0})
    a = acct_map["schwab_rollover_ira"]
    assert a["visible_cash_usd"] == 20000.0
    assert a["open_claims_usd"] == 35082.0
    assert a["currently_allocatable_usd"] == 20000.0
    assert rows[0]["capital_status"] == "claim_within_capital"  # older sale wins
    assert rows[1]["capital_status"] == "awaiting_capital"
    assert a["overclaimed"] is True
    assert a["overclaim_usd"] == 15082.0
    # shortfall = 17541 - (20000 - 17541) = 15082
    assert "capital_overclaimed_awaiting_$15082.00" in rows[1]["warnings"]


def test_awaiting_capital_when_claims_exceed_visible_cash():
    cb = _ledger_mod()
    rows = [
        _row(1, remaining=100.0, sold_at="2026-06-01"),
        _row(2, remaining=100.0, sold_at="2026-06-02"),
        _row(3, remaining=100.0, sold_at="2026-06-03"),
    ]
    acct_map = cb.apply_capital_ledger(rows, {"schwab_rollover_ira": 250.0})
    statuses = [r["capital_status"] for r in rows]
    assert statuses == ["claim_within_capital", "claim_within_capital", "awaiting_capital"]
    assert any(w.startswith("capital_overclaimed_awaiting_$") for w in rows[2]["warnings"])
    a = acct_map["schwab_rollover_ira"]
    assert a["overclaimed"] is True
    assert a["overclaim_usd"] == 50.0


def test_locked_beats_unlocked_regardless_of_age():
    """A locked plan reserves capital even though its sale is newer."""
    cb = _ledger_mod()
    rows = [
        _row(10, remaining=800.0, sold_at="2026-06-01"),                     # oldest, unlocked
        _row(11, remaining=700.0, sold_at="2026-06-20", locked_plan_id=99),  # newest, locked
    ]
    acct_map = cb.apply_capital_ledger(rows, {"schwab_rollover_ira": 1000.0})
    a = acct_map["schwab_rollover_ira"]
    assert rows[1]["capital_status"] == "reserved_locked"
    assert a["locked_reservation_usd"] == 700.0
    # Only 300 remains allocatable, so the older-but-unlocked event must wait.
    assert a["currently_allocatable_usd"] == 300.0
    assert rows[0]["capital_status"] == "awaiting_capital"
    assert "capital_overclaimed_awaiting_$500.00" in rows[0]["warnings"]


def test_selected_reservation_beats_plain_open():
    cb = _ledger_mod()
    rows = [
        _row(20, remaining=600.0, sold_at="2026-06-01"),                         # oldest, plain
        _row(21, remaining=600.0, sold_at="2026-06-15", operator_status="reviewing"),
    ]
    acct_map = cb.apply_capital_ledger(rows, {"schwab_rollover_ira": 1000.0})
    a = acct_map["schwab_rollover_ira"]
    assert rows[1]["capital_status"] == "reserved_selected"
    assert a["selected_reservation_usd"] == 600.0
    assert a["currently_allocatable_usd"] == 400.0
    assert rows[0]["capital_status"] == "awaiting_capital"


def test_totals_arithmetic_and_deployable_untouched():
    cb = _ledger_mod()
    rows = [
        _row(30, remaining=500.0, deployed=250.0, locked_plan_id=5,
             completion_status="partial", sold_at="2026-06-01"),
        _row(31, remaining=300.0, operator_status="selected", sold_at="2026-06-02"),
        _row(32, remaining=200.0, sold_at="2026-06-03"),
        _row(33, remaining=999.0, completion_status="completed"),  # not an open claim
        _row(34, remaining=999.0, completion_status="dismissed"),
    ]
    before = [(r["remaining_usd"], r["deployed_usd"]) for r in rows]
    acct_map = cb.apply_capital_ledger(rows, {"schwab_rollover_ira": 2000.0})
    a = acct_map["schwab_rollover_ira"]
    assert a["locked_reservation_usd"] == 500.0
    assert a["selected_reservation_usd"] == 300.0
    assert a["implemented_usd"] == 250.0
    assert a["open_claims_usd"] == 500.0 + 300.0 + 200.0
    # visible - locked - selected - implemented, floored at 0
    assert a["currently_allocatable_usd"] == 2000.0 - 500.0 - 300.0 - 250.0
    assert rows[2]["capital_status"] == "claim_within_capital"
    assert a["overclaimed"] is False and a["overclaim_usd"] == 0.0
    # Closed rows are not claims and keep a null capital_status.
    assert rows[3]["capital_status"] is None and rows[4]["capital_status"] is None
    # Reservation layer must never touch reconciliation truth.
    assert [(r["remaining_usd"], r["deployed_usd"]) for r in rows] == before


def test_allocatable_floors_at_zero_and_unknown_account():
    cb = _ledger_mod()
    rows = [
        _row(40, remaining=1500.0, locked_plan_id=7, sold_at="2026-06-01"),
        _row(41, remaining=100.0, sold_at="2026-06-02"),
        _row(42, account=None, remaining=50.0, sold_at="2026-06-03"),
    ]
    acct_map = cb.apply_capital_ledger(rows, {"schwab_rollover_ira": 1000.0})
    a = acct_map["schwab_rollover_ira"]
    assert a["currently_allocatable_usd"] == 0.0  # floor, not -500
    assert rows[1]["capital_status"] == "awaiting_capital"
    # Rows without an account map to "unknown" with zero visible cash.
    u = acct_map["unknown"]
    assert u["visible_cash_usd"] == 0.0 and u["overclaimed"] is True
    assert rows[2]["capital_status"] == "awaiting_capital"


def test_cash_only_account_appears_in_ledger():
    cb = _ledger_mod()
    acct_map = cb.apply_capital_ledger([], {"alpaca_paper": 5000.0})
    a = acct_map["alpaca_paper"]
    assert a["open_claims_usd"] == 0.0
    assert a["currently_allocatable_usd"] == 5000.0
    assert a["overclaimed"] is False
