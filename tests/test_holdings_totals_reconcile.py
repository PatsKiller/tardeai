"""A holdings write may not persist totals that disagree with its positions.

2026-08-27: two copies of the AUTHORITATIVE store diverged. Measured, keyed by
(symbol, account): all 30 positions present in both, `shares` differing on 0 of
30, `price` differing on 19 of 23 symbols. The fresher copy was internally
inconsistent by exactly $3,748.04 -- and that figure equals the sum of the
per-position market_value changes, i.e. the entire gap was a repricing that
`portfolio_totals` never absorbed.

The divergence was the symptom. The defect was a bulk writer updating positions
and leaving the total alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from schwab_position_sync import reconcile_totals  # noqa: E402


def _doc(rows, stated):
    return {"holdings": [{"symbol": s, "account": a, "market_value": v} for s, a, v in rows],
            "portfolio_totals": {"total_value": stated}}


def test_the_incident_a_repriced_payload_gets_its_total_absorbed():
    doc = _doc([("A", "x", 700.0), ("B", "y", 250.0)], 1000.0)
    c = reconcile_totals(doc, source="schwab_position_sync")
    assert c["delta"] == -50.0
    assert doc["portfolio_totals"]["total_value"] == 950.0
    assert doc["portfolio_totals"]["total_value_recomputed_at_write"] is True


def test_a_consistent_payload_is_left_alone():
    doc = _doc([("A", "x", 700.0), ("B", "y", 300.0)], 1000.0)
    assert reconcile_totals(doc) is None
    assert "total_value_recomputed_at_write" not in doc["portfolio_totals"]


def test_same_symbol_in_two_accounts_is_counted_twice():
    """SCHD, SPCX, V and CASH are each held in more than one account. A
    symbol-keyed sum silently drops the second row -- that mistake understated
    the live delta as -3,385.38 instead of -3,748.04."""
    doc = _doc([("SCHD", "taxable", 14285.94), ("SCHD", "rollover", 351408.81)], 0.0)
    reconcile_totals(doc)
    assert doc["portfolio_totals"]["total_value"] == 365694.75


def test_sub_cent_noise_is_not_a_correction():
    doc = _doc([("A", "x", 1000.004)], 1000.0)
    assert reconcile_totals(doc) is None


# ── it must not weaken the wipe guard ──────────────────────────────────────

def test_an_empty_payload_is_never_given_a_total():
    """The wipe-guard's whole job. Recompute must not manufacture 0.0 and
    make a wipe look like a legitimate write."""
    doc = {"holdings": [], "portfolio_totals": {"total_value": 1_288_000.0}}
    assert reconcile_totals(doc) is None
    assert doc["portfolio_totals"]["total_value"] == 1_288_000.0


def test_it_unmasks_a_collapse_hidden_behind_a_healthy_declared_total():
    """holdings_sanity uses `declared if declared > 0 else summed`, so a stale
    healthy total hides a real collapse from the catastrophic-drop check.
    Recomputing before validation is what closes that."""
    from holdings_sanity import REQUIRED_ACCOUNTS, validate_payload

    # Every governed account must be present and material, or validation stops
    # on INCOMPLETE_ACCOUNTS and never reaches the drop check being tested.
    def book(per_account):
        return _doc([(f"S{i}", a, per_account) for i, a in enumerate(REQUIRED_ACCOUNTS)],
                    1_000_000.0)

    prior = book(1_000_000.0 / len(REQUIRED_ACCOUNTS))
    prior["portfolio_totals"]["total_value"] = 1_000_000.0
    collapsed = book(10_000.0)          # positions collapsed, declared total stale

    assert validate_payload(collapsed, prior).ok, "documents today's blind spot"
    reconcile_totals(collapsed, source="test")
    assert not validate_payload(collapsed, prior).ok, "recompute must unmask it"


def test_bad_input_never_raises():
    for bad in ({}, {"holdings": None}, {"holdings": [{"symbol": "A"}]},
                {"holdings": [{"market_value": "abc"}], "portfolio_totals": {}}):
        reconcile_totals(bad)


# ── total_cash is the same defect one field later (2026-11-03 18:37:12Z) ───────────────────────────────
def _cash_doc(rows, declared_cash, declared_value=None):
    value = sum(v for _, _, v in rows) if declared_value is None else declared_value
    return {"holdings": [{"symbol": s, "account": a, "market_value": v, **({"is_cash": True} if s == "CASH" else {})}
                         for s, a, v in rows],
            "portfolio_totals": {"total_value": value, "total_cash": declared_cash}}


def test_a_writer_that_changes_cash_rows_gets_total_cash_reconciled():
    """The live case: schwab_position_sync bought PFE, cash fell 30,450.00, total_cash stayed at the
    figure the 18:30:43Z repricer had written. The store then read 847,552.75 against rows summing to
    817,102.75 while total_value was correct to the cent."""
    rows = [("CASH", "moomoo", 500.00), ("CASH", "alpaca", 5000.00), ("CASH", "schwab_taxable", 33583.83),
            ("CASH", "schwab_roth", 628.31), ("CASH", "schwab_rollover", 777390.61)]
    doc = _cash_doc(rows, declared_cash=847552.75)
    c = reconcile_totals(doc, source="schwab_position_sync")

    assert c["field"] == "total_cash" and c["delta"] == -30450.00
    assert doc["portfolio_totals"]["total_cash"] == 817102.75
    assert doc["portfolio_totals"]["total_cash_source"] == "position_rows"
    assert doc["portfolio_totals"]["total_cash_recomputed_at_write"] is True
    assert "total_value_recomputed_at_write" not in doc["portfolio_totals"]


def test_cash_is_summed_across_accounts_not_by_symbol():
    """CASH is one symbol in five accounts; a symbol-keyed sum would report a fifth of the truth."""
    doc = _cash_doc([("CASH", "a", 500.0), ("CASH", "b", 5000.0), ("CASH", "c", 1000.0)], declared_cash=0.0)
    reconcile_totals(doc)
    assert doc["portfolio_totals"]["total_cash"] == 6500.0


def test_a_consistent_cash_total_is_left_alone():
    doc = _cash_doc([("CASH", "a", 500.0), ("X", "a", 1500.0)], declared_cash=500.0)
    assert reconcile_totals(doc) is None
    assert "total_cash_recomputed_at_write" not in doc["portfolio_totals"]


def test_no_cash_rows_leaves_total_cash_untouched():
    doc = _cash_doc([("A", "x", 1000.0)], declared_cash=999.0)
    assert reconcile_totals(doc) is None
    assert doc["portfolio_totals"]["total_cash"] == 999.0


def test_both_totals_are_reconciled_in_one_write():
    doc = _cash_doc([("CASH", "a", 500.0), ("A", "x", 900.0)], declared_cash=700.0, declared_value=1000.0)
    c = reconcile_totals(doc)
    assert c["delta"] == 400.0 and c["total_cash"]["delta"] == -200.0
    assert doc["portfolio_totals"]["total_value"] == 1400.0
    assert doc["portfolio_totals"]["total_cash"] == 500.0
