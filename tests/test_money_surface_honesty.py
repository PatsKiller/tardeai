"""Two money surfaces that told the operator something untrue.

Both were found by reading a rendered number and asking which quantity it was.

3a — `reentry_total` sat in the field position that reads as the total of the
list above it, and was a three-way branch: the NEAR+REENTER overlay, else the
whole Surface A book, else the queue pipe. With one chip in the list it read 7.
The map that binds fields to pipes did not mention the field at all.

3b — the capital plan stamped its cash with the composition clock. Measured on
the live book 2026-08-30 the five cash rows spanned 27 days: $500 last confirmed
2026-08-03 and $625,284 of Schwab cash on 2026-08-14, all presented as of today.
"""
from __future__ import annotations

from scripts.lib import cio_capital_plan as cp
from scripts.lib.cio_command_center import (
    build_capital_plan,
    overlay_surface_a_reentry_on_opportunities,
)


# ── 3a — one field, one book, always ───────────────────────────────────────

def _overlay(queue_total, count, near, reenter):
    return overlay_surface_a_reentry_on_opportunities(
        {"reentry": [], "reentry_total": queue_total},
        {"count": count, "counts": {"NEAR": near, "REENTER": reenter}},
    )


def test_the_total_is_the_book_in_every_branch_that_used_to_differ():
    """The three old branches, now agreeing on what the field means."""
    # Branch 1: actionable names exist. Was the overlay (7); now the book.
    assert _overlay(3, 67, 5, 2)["reentry_total"] == 67
    # Branch 2: book with nothing actionable. Was already the book.
    assert _overlay(3, 67, 0, 0)["reentry_total"] == 67
    # Branch 3: empty book. Was the queue's total (3) — a different population
    # rendered as this book's total. Now honestly zero.
    assert _overlay(3, 0, 0, 0)["reentry_total"] == 0


def test_the_actionable_subset_kept_its_number_under_its_own_name():
    out = _overlay(3, 67, 5, 2)
    assert out["reentry_actionable"] == 7
    assert out["queue_reentry_total"] == 3
    # Nothing was lost by binding the total; all three are addressable.
    assert out["surface_a_reentry_count"] == 67


def test_every_rendered_count_is_in_the_pipes_map():
    out = _overlay(3, 67, 5, 2)
    pipes = out["reentry_pipes"]
    for field in ("reentry_total", "reentry_actionable", "queue_reentry_total"):
        assert field in pipes, f"{field} is rendered but unmapped"
        assert isinstance(pipes[field], str) and len(pipes[field]) > 20
    assert pipes["merged"] is False


def test_the_two_pipes_are_still_never_summed():
    out = _overlay(3, 67, 5, 2)
    assert out["reentry_total"] != out["reentry_total"] + out["queue_reentry_total"]
    assert "never summed" in out["reentry_pipes"]["queue_reentry_total"]


# ── 3b — the cash block dates itself ───────────────────────────────────────

_ROWS = [
    {"symbol": "CASH", "is_cash": True, "market_value": 500.0,
     "account": "moomoo", "canonical_mark_as_of": "2026-08-03"},
    {"symbol": "CASH", "is_cash": True, "market_value": 585_917.80,
     "account": "schwab_rollover", "canonical_mark_as_of": "2026-08-14",
     "as_of": "2026-08-26"},
    {"symbol": "NVDA", "market_value": 10_000.0, "account": "schwab_taxable"},
]


def test_the_block_is_as_old_as_its_stalest_account():
    ev = cp.cash_evidence_as_of(_ROWS, {"as_of": "2026-08-30"})
    assert ev["as_of"] == "2026-08-03"
    assert ev["newest_row_as_of"] == "2026-08-14"
    assert ev["mixed_ages"] is True
    # The document's own newer stamp must not overwrite the rows' evidence.
    assert ev["document_as_of"] == "2026-08-30"


def test_the_broker_confirmation_beats_the_collectors_date():
    """The Schwab row carries both: confirmed 08-14, collected 08-26. The
    conservative one wins, or the block claims freshness it does not have."""
    ev = cp.cash_evidence_as_of(_ROWS)
    schwab = [r for r in ev["by_account"] if r["account"] == "schwab_rollover"][0]
    assert schwab["as_of"] == "2026-08-14"


def test_an_unstamped_row_is_a_visible_absence_not_a_borrowed_clock():
    ev = cp.cash_evidence_as_of(
        [{"is_cash": True, "market_value": 1.0, "account": "mystery"}],
        {"as_of": "2026-08-30"},
    )
    assert ev["as_of"] is None
    assert ev["unstamped"] is True
    assert ev["unstamped_accounts"] == ["mystery"]


def test_no_derived_stamp_is_ever_the_moment_the_builder_ran():
    """The whole defect in one assertion."""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    ev = cp.cash_evidence_as_of(_ROWS, {"as_of": today, "generated_at": today})
    assert ev["as_of"] != today
    for r in ev["by_account"]:
        assert r["as_of"] != today


def test_the_surface_carries_the_cash_clock_not_only_the_envelope():
    plan = {"cash_total_usd": 1000.0,
            "as_of": "2026-08-30T21:00:00+00:00",
            "cash_as_of": cp.cash_evidence_as_of(_ROWS)}
    surf = build_capital_plan(plan)
    assert surf["cash_as_of"]["as_of"] == "2026-08-03"


def test_a_plan_without_a_cash_clock_says_so_rather_than_inheriting_one():
    surf = build_capital_plan({"cash_total_usd": 1000.0, "as_of": "2026-08-30"})
    assert surf["cash_as_of"]["as_of"] is None
    assert surf["cash_as_of"]["unstamped"] is True
