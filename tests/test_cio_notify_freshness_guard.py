"""An advisory may not quote a portfolio figure current truth contradicts.

2026-08-30: a live S6 plan was one wake away from telling the operator
"cash is elevated at 805800" when cash was 630,784.82 — a $175,015
overstatement frozen into LLM prose on 2026-08-26. It was material, in-bar,
and passed every existing gate. Formatting complaints are cosmetic; this one
is correctness, so the guard fails CLOSED.
"""
import json
from pathlib import Path

import pytest

from scripts.lib.cio_notify_freshness import (
    TOLERANCE_PCT, current_cash, describe, stale_claim,
)

ACTUAL = 630784.82


@pytest.fixture
def book(tmp_path):
    d = tmp_path / "data" / "portfolios" / "state"
    d.mkdir(parents=True)
    (d / "holdings.json").write_text(
        json.dumps({"portfolio_totals": {"total_cash": ACTUAL}}), encoding="utf-8")
    return tmp_path


def test_the_live_case_is_blocked(book):
    """Verbatim from plan_40c316cee82c."""
    plan = {"summary": "Portfolio heat is very low at 0.09%, and cash is "
                       "elevated at 805800, providing ample buffer."}
    hit = stale_claim(plan, root=book)
    assert hit
    assert hit["claimed"] == 805800.0
    assert hit["actual"] == ACTUAL
    assert hit["drift_pct"] > 25
    assert hit["reason"] == "narrative_quotes_stale_cash"


@pytest.mark.parametrize("text", [
    "Cash stands at 630,784.82 as of today.",
    "$630,784 in cash provides the buffer.",
    "cash is 630785",
])
def test_a_correct_figure_passes(book, text):
    assert stale_claim({"summary": text}, root=book) is None


@pytest.mark.parametrize("text", [
    "No catalyst; RSI=50.56; portfolio heat 0.09%.",
    "Weight is 12.4% against a 12% review threshold.",
    "Held 36.0 months with a 100.0pct disposition loss.",
    "",
])
def test_prose_without_a_cash_claim_is_untouched(book, text):
    """This is a claim checker, not a numeric scanner. Silence is not the goal."""
    assert stale_claim({"summary": text}, root=book) is None


def test_it_abstains_when_the_book_cannot_be_read(tmp_path):
    """Never block on our own blindness — that would silence the desk."""
    plan = {"summary": "cash is elevated at 805800"}
    assert current_cash(tmp_path) is None
    assert stale_claim(plan, root=tmp_path) is None


def test_small_drift_is_tolerated(book):
    """Rounding in prose must not gag a good advisory."""
    near = ACTUAL * (1 + (TOLERANCE_PCT - 1) / 100.0)
    assert stale_claim({"summary": f"cash near {near:,.0f}"}, root=book) is None


def test_it_reads_every_field_that_reaches_the_operator(book):
    for field in ("summary", "recommendation", "thesis_alignment",
                  "multi_domain_summary"):
        assert stale_claim({field: "cash is elevated at 805800"}, root=book), field


def test_describe_explains_itself(book):
    d = describe({"summary": "cash is elevated at 805800"}, root=book)
    assert d["block_notify"] is True
    assert d["claim"]["drift_pct"] > 25
    assert d["authority"] == "READ_ONLY_ADVISORY"


def test_the_notify_path_is_actually_wired_to_it():
    """A guard not wired to its input is the failure this session kept finding."""
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "lib" / "cio_plan_enrichment.py").read_text(encoding="utf-8")
    assert "cio_notify_freshness" in src
    assert "narrative_quotes_stale_cash" in src


# --- the identifier form, missed by the first cut (2026-08-30) --------------
#
# `\bcash\b` needs a word boundary, but `total_cash=` and `cash_buying_power`
# sit next to underscores, which ARE word characters. The guard passed a plan
# as clean and it delivered `total_cash=578107.50` against an actual
# 630,784.82 — 8.4% off — to the operator's phone.

def test_the_snake_case_identifier_form_is_caught(book):
    plan = {"multi_domain_summary":
            "Domains cash_buying_power, risk: cash_buying_power("
            "total_cash=578107.50); portfolio(total_value=1277811.05)"}
    hit = stale_claim(plan, root=book)
    assert hit, "the delivered-message form must not pass"
    assert hit["claimed"] == 578107.50
    assert 8.0 < hit["drift_pct"] < 9.0


def test_the_same_identifier_carrying_truth_passes(book):
    assert stale_claim(
        {"multi_domain_summary": f"cash_buying_power(total_cash={ACTUAL})"},
        root=book) is None


@pytest.mark.parametrize("text", [
    "free_cashflow_yield was 12000 bps",      # cashflow is not cash
    "cashless_exercise of 45000 units",
])
def test_words_merely_containing_cash_do_not_match(book, text):
    assert stale_claim({"summary": text}, root=book) is None
