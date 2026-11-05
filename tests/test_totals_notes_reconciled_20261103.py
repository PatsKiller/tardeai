"""TOTALS_NOTES_RECONCILED_20261103 — a stale note cannot outlive the totals it describes.

The live store on 2026-11-03 carried this beside a populated `day_change`:

    note            "rebuilt from positions_current run 638; day change not carried"
    day_change      -2998.49
    day_change_note "seeded 0.0 on 2026-11-03 by lead: unknown until the next repricer pass
                     computes it from live quotes; not a measured value"

The repricer rewrites `day_change` every 15 minutes and had no notion of the note, so the false
claim was rewritten true-beside-false on every cycle — a provenance statement that reads as a
current fact. `_recalc_totals` now reconciles the notes against the totals it just computed.

These tests drive the real `_recalc_totals` over a book shaped like the live document, and pin the
three things that matter: the falsified text goes, the still-true text stays, and a pass that did
not compute a day change clears nothing.
"""
from __future__ import annotations

import pytest

from scripts.portfolio_repricer import _recalc_totals, _reconcile_totals_notes

LIVE_NOTE = "rebuilt from positions_current run 638; day change not carried"
LIVE_DAY_CHANGE_NOTE = ("seeded 0.0 on 2026-11-03 by lead: unknown until the next repricer pass "
                        "computes it from live quotes; not a measured value")
LIVE_BASIS_NOTE = ("aggregate basis/P&L left NULL: 2 non-cash row(s) have no sourced basis — "
                   "partial sums are not published as totals")


@pytest.fixture()
def book():
    """A two-account book carrying the live document's note text verbatim."""
    return {
        "as_of": "2026-11-03",
        "holdings": [
            {"symbol": "CASH", "account": "schwab_taxable", "is_cash": True, "market_value": 1_000.00},
            {"symbol": "SCHD", "account": "schwab_taxable", "shares": 10.0,
             "market_value": 900.00, "cost_basis": 800.00},
        ],
        "portfolio_totals": {
            "note": LIVE_NOTE,
            "day_change_note": LIVE_DAY_CHANGE_NOTE,
            "basis_note": LIVE_BASIS_NOTE,
            "basis_complete": False,
            "day_change": 0.0,
        },
        "account_summaries": {"schwab_taxable": {}},
    }


def test_the_stale_clause_does_not_outlive_the_recompute(book):
    _recalc_totals(book)
    totals = book["portfolio_totals"]
    assert isinstance(totals.get("day_change"), (int, float))
    assert "not carried" not in str(totals.get("note") or ""), (
        "a note claiming the day change was not carried survived a pass that computed it")


def test_the_provenance_half_of_a_mixed_note_survives(book):
    """Only the falsified clause goes: which rebuild wrote the book is still true and still needed."""
    _recalc_totals(book)
    assert book["portfolio_totals"]["note"] == "rebuilt from positions_current run 638"


def test_a_seeded_day_change_note_is_dropped_once_the_value_is_measured(book):
    _recalc_totals(book)
    assert "day_change_note" not in book["portfolio_totals"], (
        "the note explains a seeded 0.0 that this pass replaced with a computed value")


def test_a_note_about_something_else_is_untouched(book):
    """`basis_note` describes basis coverage, which this pass does not change."""
    _recalc_totals(book)
    assert book["portfolio_totals"]["basis_note"] == LIVE_BASIS_NOTE
    assert book["portfolio_totals"]["basis_complete"] is False


def test_a_note_with_no_stale_text_is_not_rewritten(book):
    book["portfolio_totals"]["note"] = "rebuilt from positions_current run 638"
    book["portfolio_totals"].pop("day_change_note")  # the other key must be clean too
    _recalc_totals(book)
    totals = book["portfolio_totals"]
    assert totals["note"] == "rebuilt from positions_current run 638"
    assert "notes_reconciled_at" not in totals, "nothing was cleared, so nothing may be recorded"


def test_the_clearing_is_recorded_when_it_happens(book):
    _recalc_totals(book)
    assert book["portfolio_totals"]["notes_reconciled_at"]


@pytest.mark.parametrize("day_change", [None, "0.0", True])
def test_a_pass_that_did_not_compute_a_day_change_clears_nothing(day_change):
    """The rule is 'the note is falsified by what we just wrote'. No computed value, no claim."""
    totals = {"note": LIVE_NOTE, "day_change_note": LIVE_DAY_CHANGE_NOTE, "day_change": day_change}
    assert _reconcile_totals_notes(totals) == []
    assert totals["note"] == LIVE_NOTE
    assert totals["day_change_note"] == LIVE_DAY_CHANGE_NOTE


def test_a_note_that_is_entirely_stale_is_removed_not_emptied(book):
    book["portfolio_totals"]["note"] = "day change not carried"
    _recalc_totals(book)
    assert "note" not in book["portfolio_totals"], "an empty string is not a note"


def test_the_reconciler_is_wired_into_the_totals_write():
    """Structural guard: the call must sit in `_recalc_totals`, not in a caller somebody can skip."""
    import inspect
    from scripts import portfolio_repricer

    source = inspect.getsource(portfolio_repricer._recalc_totals)
    assert "_reconcile_totals_notes(" in source, "the totals write no longer reconciles its notes"
