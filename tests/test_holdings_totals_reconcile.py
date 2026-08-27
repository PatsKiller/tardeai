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
