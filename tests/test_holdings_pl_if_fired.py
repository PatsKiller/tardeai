#!/usr/bin/env python3
"""Holdings 'P/L if fired' — realized position P/L if the current stop executes.

Implementation baseline: d251c84b (holdingsRowModel.ts + HoldingsTableView.tsx).

Canonical formula (the Stop Management drawer shows the identical arithmetic):

    P/L if fired = current unrealized P/L - shares * (current price - effective stop)
                 = shares * (effective stop - cost basis per share)   [equivalent]

Effective-stop source priority:
    1. confirmed live broker protective stop (liveStopPrice)
    2. current advisory/monitored stop when no live stop exists (stopPrice)
    3. no value when neither is valid  (never silently shows 0)

This is a SPEC test: the formula is replicated here and checked across the matrix,
and the TS source is asserted to implement the same formula, priority and null
handling, and to disclose the stop source in the tooltip. Advisory only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
ROW = ROOT / "apps" / "command-center-v3" / "src" / "lib" / "holdingsRowModel.ts"
TABLE = ROOT / "apps" / "command-center-v3" / "src" / "components" / "HoldingsTableView.tsx"


def pl_if_fired(pl_dollars, shares, price, live_stop, advisory_stop):
    """Reference implementation of the TS row-model computation."""
    effective_stop = live_stop if live_stop is not None else advisory_stop
    if pl_dollars is None or price is None or effective_stop is None or not (shares and shares > 0):
        return None
    return round(pl_dollars - shares * (price - effective_stop), 2)


def _pl_dollars(shares, price, cost_per_share):
    if cost_per_share is None:
        return None
    return (price - cost_per_share) * shares


# ── the two algebraic forms agree ─────────────────────────────────────────────

def test_two_forms_are_equivalent():
    shares, price, cost, stop = 100, 34.20, 30.00, 32.43
    pld = _pl_dollars(shares, price, cost)
    via_unreal = pl_if_fired(pld, shares, price, stop, None)
    via_basis = round(shares * (stop - cost), 2)
    assert via_unreal == via_basis == 243.0


# ── scenario matrix ───────────────────────────────────────────────────────────

def test_profitable_with_stop_above_cost_locks_a_gain():
    r = pl_if_fired(_pl_dollars(100, 40, 30), 100, 40, 35, None)   # stop 35 > cost 30
    assert r == 500.0 and r > 0


def test_profitable_with_stop_below_cost_is_a_loss_if_fired():
    r = pl_if_fired(_pl_dollars(100, 40, 38), 100, 40, 35, None)   # stop 35 < cost 38
    assert r == -300.0 and r < 0


def test_losing_position():
    r = pl_if_fired(_pl_dollars(100, 90, 100), 100, 90, 85, None)  # underwater, stop below
    assert r == -1500.0


def test_trailing_stop_uses_the_live_trailing_price():
    r = pl_if_fired(_pl_dollars(50, 56.58, 60), 50, 56.58, 53.76, None)
    assert r == round(50 * (53.76 - 60), 2)   # == -312.0


def test_fixed_stop():
    r = pl_if_fired(_pl_dollars(7774, 34.20, 30.0), 7774, 34.20, 32.43, None)
    assert r == round(7774 * (32.43 - 30.0), 2)


def test_advisory_stop_used_when_no_live_stop():
    # live_stop None → falls back to advisory
    r = pl_if_fired(_pl_dollars(10, 100, 90), 10, 100, None, 95)
    assert r == round(10 * (95 - 90), 2) == 50.0


def test_live_stop_takes_priority_over_advisory():
    r = pl_if_fired(_pl_dollars(10, 100, 90), 10, 100, 96, 95)   # live 96 wins over advisory 95
    assert r == round(10 * (96 - 90), 2) == 60.0


def test_no_stop_at_all_returns_none_never_zero():
    assert pl_if_fired(_pl_dollars(10, 100, 90), 10, 100, None, None) is None


def test_fractional_shares_use_broker_quantity():
    r = pl_if_fired(_pl_dollars(12.5, 100, 90), 12.5, 100, 95, None)
    assert r == round(12.5 * (95 - 90), 2) == 62.5


def test_missing_cost_basis_yields_none():
    # unrealized dollars unknown (no cost basis) → cannot compute
    assert pl_if_fired(None, 10, 100, 95, None) is None


def test_missing_price_yields_none():
    assert pl_if_fired(_pl_dollars(10, 100, 90), 10, None, 95, None) is None


def test_cash_or_zero_share_row_yields_none():
    assert pl_if_fired(0.0, 0, 1.0, None, None) is None


# ── the TS source implements exactly this ─────────────────────────────────────

def test_row_model_formula_and_priority():
    src = ROW.read_text()
    assert "liveStopPrice ?? stopPrice" in src, "effective stop = live broker stop, advisory fallback"
    assert "pl$ - sh * (cur - stopForPl)" in src, "canonical formula"
    # null-safe: requires pl$, price, an effective stop and positive shares
    assert "pl$ != null && cur != null && stopForPl != null && sh > 0" in src


def test_table_discloses_the_stop_source_in_the_tooltip():
    src = TABLE.read_text()
    assert "if fired" in src
    # the tooltip names which stop the figure is measured against
    assert "live broker stop" in src and "advisory stop" in src
