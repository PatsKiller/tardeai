"""Cash display law while the two writers disagree (operator judgment 2026-08-29).

    Do not average. Do not pick a winner in the renderer.
    Both numbers are already on the same session; collapsing them is how you
    hide a writer bug.

    cash_rows      630784.82   source=position_rows
    cash_totals    578107.50   source=portfolio_totals
    cash_gap        52677.32   status=UNRECONCILED
    cash_for_S5    DATA_UNAVAILABLE_UNTIL_RECONCILED
"""
from __future__ import annotations

import pytest

from scripts.lib import holdings_universe as hu
from scripts.lib.cio_operator_renderers import cash_lines

LIVE_GAP = 52_677.32


def _doc(rows_total, declared):
    return {
        "as_of": "2026-08-29",
        "generated_at": "2026-08-29 09:00:00",
        "portfolio_totals": {"total_cash": declared},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": rows_total,
             "account": "ira"},
            {"symbol": "SCHD", "market_value": 1000.0},
        ],
    }


def test_disagreement_is_named_not_collapsed(monkeypatch):
    monkeypatch.setattr(hu, "load_holdings_doc",
                        lambda *, root=None: _doc(630_784.82, 578_107.50))
    c = hu.cash_total_sources()
    assert c["cash_row_sum"] == 630_784.82
    assert c["portfolio_totals_total_cash"] == 578_107.50
    assert c["cash_gap"] == LIVE_GAP
    assert c["cash_status"] == "UNRECONCILED"
    assert c["merged"] is False and c["reconciled"] is False


def test_s5_refuses_a_number_while_the_gap_is_open(monkeypatch):
    monkeypatch.setattr(hu, "load_holdings_doc",
                        lambda *, root=None: _doc(630_784.82, 578_107.50))
    assert hu.cash_total_sources()["cash_for_s5"] == "DATA_UNAVAILABLE_UNTIL_RECONCILED"


def test_s5_gets_a_number_once_the_writers_agree(monkeypatch):
    monkeypatch.setattr(hu, "load_holdings_doc",
                        lambda *, root=None: _doc(1000.0, 1000.0))
    c = hu.cash_total_sources()
    assert c["cash_status"] == "RECONCILED"
    assert c["cash_for_s5"] == 1000.0


def test_both_sources_are_labelled_with_their_role(monkeypatch):
    monkeypatch.setattr(hu, "load_holdings_doc",
                        lambda *, root=None: _doc(630_784.82, 578_107.50))
    src = hu.cash_total_sources()["sources"]
    assert src["position_rows"]["value"] == 630_784.82
    assert src["portfolio_totals"]["value"] == 578_107.50
    assert src["position_rows"]["role"] != src["portfolio_totals"]["role"]


def test_the_writer_is_not_yet_identified(monkeypatch):
    """Honest state: the gap is detected, the cause is not yet named."""
    monkeypatch.setattr(hu, "load_holdings_doc",
                        lambda *, root=None: _doc(630_784.82, 578_107.50))
    c = hu.cash_total_sources()
    assert c["writer_identified"] is False
    assert "identify the totals writer" in c["next_slice"]


# ── the renderer ─────────────────────────────────────────────────────────────

DISAGREE = {"cash": {"cash_usd": 630_784.82},
            "temperament": {"cash": 578_107.50, "cash_pct": 44.88}}


def test_brief_prints_all_four_lines_and_picks_nothing():
    body = "\n".join(cash_lines(DISAGREE))
    assert "cash_rows" in body and "630,784.82" in body
    assert "cash_totals" in body and "578,107.50" in body
    assert "cash_gap" in body and "52,677.32" in body
    assert "status=UNRECONCILED" in body
    assert "DATA_UNAVAILABLE_UNTIL_RECONCILED" in body


@pytest.mark.parametrize("forbidden", ["604,446", "604446", "604,446.16", "≈"])
def test_the_brief_never_prints_an_averaged_value(forbidden):
    """The midpoint of 630,784.82 and 578,107.50 must never appear.

    Checking for the word "average" would be wrong — the line legitimately says
    "not merged, not averaged". It is the *number* that must not exist.
    """
    assert forbidden not in "\n".join(cash_lines(DISAGREE))


def test_the_brief_says_it_did_not_merge():
    assert "not merged, not averaged" in "\n".join(cash_lines(DISAGREE))


def test_the_brief_does_not_lead_with_one_figure_while_unreconciled():
    """It previously printed temperament.cash as *the* cash number."""
    lines = cash_lines(DISAGREE)
    assert not lines[0].startswith("Cash (live")
    assert lines[0].startswith("cash_rows")


def test_agreeing_writers_get_the_ordinary_one_line_form():
    lines = cash_lines({"cash": {"cash_usd": 1000.0},
                        "temperament": {"cash": 1000.0, "cash_pct": 10.0}})
    assert len(lines) == 1
    assert "UNRECONCILED" not in lines[0]


# ── the crash this nearly shipped with ───────────────────────────────────────

def test_non_numeric_cash_does_not_take_the_brief_down():
    """`temperament.cash` is not always a number.

    A real payload carries strings such as "hold reserve". float() on that
    raised inside the renderer and took the whole morning brief with it —
    introduced when cash_lines was first added to the brief and caught only by
    running the wider suite. Every read now goes through a numeric guard.
    """
    lines = cash_lines({
        "cash": {"cash_usd": "hold reserve"},
        "temperament": {"cash": "hold reserve"},
    })
    assert len(lines) == 1
    assert "UNAVAILABLE" in lines[0]
    assert "non-numeric" in lines[0]


def test_a_present_but_unusable_value_is_named_not_dropped():
    lines = cash_lines({"cash": {"cash_usd": None}, "temperament": {"cash": "n/a"}})
    assert "non-numeric" in lines[0]


def test_rows_only_still_renders():
    lines = cash_lines({"cash": {"cash_usd": 500.0}, "temperament": {}})
    assert "position rows" in lines[0] and "$500" in lines[0]


def test_absent_cash_is_still_the_plain_unavailable_line():
    lines = cash_lines({})
    assert lines == ["Cash: UNAVAILABLE — no live temperament cash on the product."]
