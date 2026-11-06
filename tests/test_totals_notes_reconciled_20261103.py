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

import re

import pytest

from scripts.portfolio_repricer import _recalc_totals, _reconcile_totals_notes

#: AGENTS.md "Time discipline": every stored timestamp is UTC ISO-8601 with an explicit ``Z``.
#: ``+00:00`` names the same instant but leaves the zone to be inferred from the format.
_STORED_UTC_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")

LIVE_NOTE = "rebuilt from positions_current run 638; day change not carried"
LIVE_DAY_CHANGE_NOTE = ("seeded 0.0 on 2026-11-03 by lead: unknown until the next repricer pass "
                        "computes it from live quotes; not a measured value")
LIVE_BASIS_NOTE = ("aggregate basis/P&L left NULL: 2 non-cash row(s) have no sourced basis — "
                   "partial sums are not published as totals")


@pytest.fixture()
def book():
    """A two-account book carrying the live document's note text verbatim.

    The rows carry REAL day changes (cc-deepseek-5 R1): the original fixture left them out, so the only reason
    the totals held a number was the ``or 0`` coercion — which is precisely the state in which this pass must
    NOT clear the note. Clearing is tested on a book that actually measured something."""
    return {
        "as_of": "2026-11-03",
        "holdings": [
            {"symbol": "CASH", "account": "schwab_taxable", "is_cash": True, "market_value": 1_000.00,
             "day_change": 0.0},
            {"symbol": "SCHD", "account": "schwab_taxable", "shares": 10.0,
             "market_value": 900.00, "cost_basis": 800.00, "day_change": -12.50},
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


@pytest.fixture()
def unmeasured_book(book):
    """The same book with no usable prior close on any row: the operator's own wording, still true.

    A deep copy, not the fixture's own rows: both fixtures are built before the test body runs, so mutating the
    shared list would empty the measured book as well."""
    import copy

    doc = copy.deepcopy(book)
    for row in doc["holdings"]:
        row.pop("day_change", None)
    return doc


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
    stamp = book["portfolio_totals"]["notes_reconciled_at"]
    assert isinstance(stamp, str) and _STORED_UTC_Z.fullmatch(stamp), (
        f"a stored timestamp must be UTC ISO-8601 with an explicit Z, got {stamp!r}")


@pytest.mark.parametrize("day_change", [None, "0.0", True])
def test_a_pass_that_did_not_compute_a_day_change_clears_nothing(day_change):
    """The rule is 'the note is falsified by what we just wrote'. No computed value, no claim."""
    totals = {"note": LIVE_NOTE, "day_change_note": LIVE_DAY_CHANGE_NOTE, "day_change": day_change}
    assert _reconcile_totals_notes(totals, day_change_measured_rows=1) == []
    assert totals["note"] == LIVE_NOTE
    assert totals["day_change_note"] == LIVE_DAY_CHANGE_NOTE


def test_a_total_built_entirely_from_coerced_zeros_clears_nothing(unmeasured_book):
    """cc-deepseek-5 R1, the mirror of the bug this PR exists to fix.

    ``_recalc_totals`` sums ``h.get("day_change") or 0``, so a book where NOTHING could be measured still
    produces ``day_change: 0.0`` — a number that looks computed. The blocked head cleared both notes in that
    same pass, deleting the one sentence that said the zero was not a measurement. The operator then read a
    confident 0.0 with no explanation: the false-healthy class, inverted."""
    _recalc_totals(unmeasured_book)
    totals = unmeasured_book["portfolio_totals"]
    assert totals["day_change"] == 0.0, "the sum still coerces; that is the condition under test"
    assert totals["day_change_measured_rows"] == 0
    assert totals["note"] == LIVE_NOTE, "a note that is still TRUE was deleted"
    assert totals["day_change_note"] == LIVE_DAY_CHANGE_NOTE, "the explanation of the 0.0 was deleted"
    assert "notes_reconciled_at" not in totals, "nothing was falsified, so nothing may be recorded"


def test_the_totals_say_how_the_day_change_was_arrived_at(book, unmeasured_book):
    """The fact the decision stands on travels on the document, not only in the branch that reads it."""
    _recalc_totals(book)
    assert book["portfolio_totals"]["day_change_measured_rows"] == 2
    assert book["portfolio_totals"]["day_change_unmeasured_rows"] == 0
    _recalc_totals(unmeasured_book)
    assert unmeasured_book["portfolio_totals"]["day_change_measured_rows"] == 0
    assert unmeasured_book["portfolio_totals"]["day_change_unmeasured_rows"] == 2


def test_a_partly_measured_book_clears_and_states_what_was_not(book):
    """One real value is a measurement: the note's claim ("nothing was carried") is false. The row that could
    not be read still shows up in the count, so the total is not presented as complete."""
    book["holdings"][0].pop("day_change")          # the cash row has no prior close; SCHD's -12.50 remains real
    _recalc_totals(book)
    totals = book["portfolio_totals"]
    assert totals["day_change_measured_rows"] == 1
    assert totals["day_change_unmeasured_rows"] == 1
    assert "not carried" not in str(totals.get("note") or "")
    assert "day_change_note" not in totals


def test_a_measured_row_the_total_never_summed_does_not_clear_the_note(book):
    """Third case, found by hunting my own repair after cc5's block.

    ``gd`` sums per ACCOUNT (`ah` = that account's non-loan rows), not every holding. A measured day change on a
    loan row, or on a row filed under an account with no summary, is real but is NOT part of the number the note
    describes — counting it as "we measured something" would clear the note one level down, beside a total that
    was still built entirely from coerced zeros."""
    for row in book["holdings"]:
        row.pop("day_change", None)
    book["holdings"].append({"symbol": "LOANX", "account": "schwab_taxable", "is_loan": True,
                             "market_value": 0.0, "day_change": 5.0})
    book["holdings"].append({"symbol": "ORPHAN", "account": "not_in_summaries",
                             "market_value": 0.0, "day_change": 5.0})
    _recalc_totals(book)
    totals = book["portfolio_totals"]
    assert totals["day_change_measured_rows"] == 0, "a row the sum never consumed was counted as a measurement"
    assert totals["note"] == LIVE_NOTE
    assert totals["day_change_note"] == LIVE_DAY_CHANGE_NOTE
    assert "notes_reconciled_at" not in totals


def test_a_note_that_is_entirely_stale_is_removed_not_emptied(book):
    book["portfolio_totals"]["note"] = "day change not carried"
    _recalc_totals(book)
    assert "note" not in book["portfolio_totals"], "an empty string is not a note"


def test_the_reconciler_is_wired_into_the_totals_write(book, monkeypatch):
    """Behavioural guard: the real `_recalc_totals` must EXECUTE the reconciler.

    The first version of this guard asserted that ``"_reconcile_totals_notes("`` appeared in
    ``inspect.getsource(_recalc_totals)``. ``getsource`` includes comments, so commenting the call
    out left the assertion green while the wiring was gone (codex-cloud CX1). A spy on the real
    module function proves the call is executed: comment the call out and this test goes red.
    """
    from scripts import portfolio_repricer

    real = portfolio_repricer._reconcile_totals_notes
    calls = []

    def spy(totals, *, day_change_measured_rows):
        calls.append(day_change_measured_rows)
        return real(totals, day_change_measured_rows=day_change_measured_rows)

    monkeypatch.setattr(portfolio_repricer, "_reconcile_totals_notes", spy)
    _recalc_totals(book)

    assert calls, "the totals write never executed the reconciler: a stale note would outlive the pass"
