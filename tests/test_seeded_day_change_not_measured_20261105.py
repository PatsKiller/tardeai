"""SEEDED_DAY_CHANGE_NOT_MEASURED_20261105 — an unmeasured day change may not pass as a measured zero.

codex-cloud P1 on PR #2588, 2026-11-05:

    scripts/portfolio_repricer.py:94 — "For Fidelity fund rows, portfolio_loader.py seeds
    day_change with 0.0, and _apply_to_holdings()' Fidelity NAV branch updates the mark
    without recomputing."

The loader cannot compute a day change from a Fidelity statement (there is no previous close
in it), and a proprietary fund's stale/implausible percentage cannot be trusted either — so it
used to write 0.0. The repricer counts a row as measured whenever ``day_change`` is a number,
so that seeded 0.0 counted as evidence for the totals note. The Fidelity NAV branch then moved
the mark but never touched ``day_change``, so the seeded value outlived the price it no longer
described.

These tests pin three things:

  * a row the loader could not measure carries ``None`` and the coverage counts it unmeasured;
  * a genuine measured 0.00 still counts as measured (the positive control against
    over-tightening the predicate);
  * the NAV branch recomputes from a real previous NAV, and leaves the change unmeasured when
    it has none — never inventing a value.
"""
from __future__ import annotations

import pytest

from scripts.portfolio_loader import parse_fidelity_pdf_text
from scripts.portfolio_repricer import _apply_to_holdings, _day_change_coverage


def _fidelity_statement_lines() -> list[str]:
    """Minimal NetBenefits statement text: one fund, the two skipped tier totals, six values.

    Synthetic values only (the repository is public). The date is what the parser reads for
    ``as_of``; the amounts exist only to satisfy the statement layout.
    """
    return [
        "Statement Period: 12/31/2025 to 04/30/2026",
        "Market Value of Your Account",
        "$530,241.63",       # tier total 1, skipped
        "$519,361.68",       # tier total 2, skipped
        "SP 500 Index",
        "PL CL D",
        "$100.00",           # Dec shares
        "$100.00",           # Apr shares
        "$50.00",            # Dec price
        "$55.00",            # Apr price
        "$5,000.00",         # Dec market value
        "$5,500.00",         # Apr market value
        "Account Totals",
    ]


def _fidelity_row(**overrides) -> dict:
    row = {
        "symbol": "SP500-D",
        "account": "fidelity_401k",
        "broker": "fidelity",
        "shares": 100.0,
        "market_value": 10_000.0,
        "canonical_mark": 100.0,
        "day_change": None,
        "day_change_pct": None,
    }
    row.update(overrides)
    return row


def test_fidelity_statement_rows_are_not_seeded_as_a_measured_zero():
    """The statement has no previous close, so the row's day change is unknown — not 0.0."""
    parsed = parse_fidelity_pdf_text(_fidelity_statement_lines())
    assert "error" not in parsed, parsed
    row = parsed["holdings"][0]
    assert row["day_change"] is None, "an unmeasurable row was seeded with a number"
    assert row["day_change_pct"] is None
    coverage = _day_change_coverage([row])
    assert coverage["day_change_measured_rows"] == 0, "a seeded zero counted as a measurement"
    assert coverage["day_change_unmeasured_rows"] == 1


def test_the_nav_branch_recomputes_from_a_measured_previous_nav():
    """A NAV mark that moves the price must move the day change with it."""
    row = _fidelity_row()
    _apply_to_holdings([row], {}, {"SP500-D": {"price": 101.0, "prev_close": 100.0,
                                               "source": "price_cache_nav"}})
    assert row["day_change"] == pytest.approx(100.0)          # (101.00 - 100.00) * 100 shares
    assert row["day_change_pct"] == pytest.approx(1.0)
    assert _day_change_coverage([row])["day_change_measured_rows"] == 1


def test_a_genuinely_measured_zero_still_counts_as_measured():
    """Positive control: the fix separates unknown from zero; it does not reject zero."""
    row = _fidelity_row()
    _apply_to_holdings([row], {}, {"SP500-D": {"price": 100.0, "prev_close": 100.0,
                                               "source": "price_cache_nav"}})
    assert row["day_change"] == 0.0
    assert row["day_change_pct"] == 0.0
    assert _day_change_coverage([row])["day_change_measured_rows"] == 1


def test_a_nav_without_a_previous_nav_leaves_the_change_unmeasured():
    """No previous NAV: the price moved but the change is unknown — never zero, never the old value."""
    row = _fidelity_row(day_change=0.0, day_change_pct=0.0)   # the old loader's seeded zero
    _apply_to_holdings([row], {}, {"SP500-D": {"price": 101.0, "source": "price_cache_nav"}})
    assert row["day_change"] is None
    assert row["day_change_pct"] is None
    assert _day_change_coverage([row])["day_change_measured_rows"] == 0
