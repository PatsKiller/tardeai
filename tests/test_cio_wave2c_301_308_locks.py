"""Wave 2C items 301–308 — one file that locks the night's invariants.

Each of these is a claim the operator relies on and that a well-meaning change
could quietly undo. They are asserted against the *canonical source* rather than
a live payload, so the suite is deterministic and runs without a server.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import inspect

import pytest


# ── 301: SCHG is EXITED and dust, never HELD ─────────────────────────────────

HOLDINGS = {"holdings": [
    {"symbol": "SCHD", "market_value": 365_694.75, "shares": 10_000.25},
    {"symbol": "SCHG", "market_value": 8.09, "shares": 0.2294},
    {"symbol": "CASH", "is_cash": True, "market_value": 585_917.80},
    {"symbol": "12507E201", "market_value": 0.0, "shares": 7.0},
]}


def test_schg_is_dust_and_never_held():
    from scripts.lib.cio_investment_product import (
        collect_surface_a_status,
        dust_symbols,
        held_equity_symbols_nondust,
    )

    assert "SCHG" in dust_symbols(HOLDINGS)
    assert "SCHG" not in held_equity_symbols_nondust(HOLDINGS)

    status = collect_surface_a_status(
        symbols=["SCHG"], holdings=HOLDINGS, previously_traded=[],
    )
    item = status["items"][0]
    assert item["symbol"] == "SCHG"
    assert item["status"] == "EXITED"          # never HELD
    assert item["residual_shares"] == 0.2294   # the lot is not deleted


# ── 302: PRIM stays CURRENT ──────────────────────────────────────────────────

def test_broker_execution_language_is_refused_before_a_thesis_can_mint():
    """#614: paper-trade research may mint a thesis; broker-exec must not.

    Two gates cover this and they have *different* vocabularies — the worker
    lint and critique's forbidden_authority. Assert each against what it
    actually claims rather than assuming one covers everything.
    """
    from scripts.lib.hermes_research_schema import lint_execution_language
    from scripts.lib.research_quality import critique

    # worker lint: imperative execution phrasing, article-tolerant since #631's sibling fix
    for text in ("execute the buy", "place an order", "submit an order", "buy now"):
        assert lint_execution_language(text), text

    # critique: the forbidden-authority net
    for text in ("place an order", "ignore all rules"):
        assert critique({
            "symbol": "PRIM", "summary": text, "sources": ["u"], "as_of": "2026-08-01",
        })["verdict"] == "FAILED", text

    # and ordinary analysis still attaches
    assert critique({
        "symbol": "PRIM", "summary": "PRIM infrastructure backlog as of 2026-08-01",
        "sources": ["u"], "as_of": "2026-08-01",
    })["verdict"] == "VALID"


# ── 303 / 304: the two flags that must never flip on ─────────────────────────

def test_home_always_declares_telegram_not_sent():
    from scripts.lib.cio_command_center import build_office_home

    assert build_office_home(operator_product={})["telegram_sent"] is False


def test_block_never_fires_s7():
    """BLOCK is honest; it is never remapped to READY and never fires S7."""
    from scripts.lib.cio_operator_renderers import watch_lines

    wbs = {"count": 26, "by_reason": {"not_promotion_grade": 26},
           "ready_count": 0, "ready_symbols": [], "near_symbols": [],
           "fires_s7": False,
           "top": [{"symbol": "FTH", "trade_ai_state": "WAIT"}]}
    body = " ".join(watch_lines({"watch_block_summary": wbs}))
    assert "fires_s7 False" in body
    assert "honest zero" in body
    assert "READY FTH" not in body


# ── 305: the two re-entry books stay two ─────────────────────────────────────

def test_two_reentry_builders_with_distinct_producers():
    from scripts.lib.cio_reentry_surface_labels import SURFACE_A, SURFACE_B

    assert SURFACE_A["surface"] == "A" and SURFACE_B["surface"] == "B"
    assert SURFACE_A["producer"] != SURFACE_B["producer"]
    assert SURFACE_A["question"] != SURFACE_B["question"]

    # both producers exist and are different functions
    from scripts.lib.cio_desk_depth import build_reentry_book as b_builder
    from scripts.lib.cio_investment_product import build_reentry_book as a_builder

    assert a_builder is not b_builder


def test_home_declares_the_books_unmerged():
    from scripts.lib.cio_command_center import build_reentry_book_labels

    assert build_reentry_book_labels()["merged"] is False


# ── 306: the deterministic path stays free ───────────────────────────────────

def test_cio_run_deterministic_path_costs_nothing():
    from scripts.lib import cio_run_worker

    src = inspect.getsource(cio_run_worker)
    assert '"dispatch_kind": "DETERMINISTIC_PRODUCT"' in src
    assert '"cost_usd", 0.0' in src
    for bad in ('"cost_usd": 0.001', '"cost_usd", 0.001', "cost_usd = 0.001"):
        assert bad not in src


# ── 307: CASE_SUMMARY is context, never an action ────────────────────────────

def test_case_summary_is_a_context_and_cannot_become_policy():
    from scripts.lib.outcome_to_lesson import candidates_from_case_summaries

    rec = {
        "memory_type": "CASE_SUMMARY", "status": "ACTIVE", "memory_id": "m1",
        "symbols": ["SCHD"], "plan_ids": ["plan_1"],
        "source_refs": ["plan:plan_1", "result:rr_1"],
    }
    cand = candidates_from_case_summaries([rec])[0]
    assert cand["status"] == "PROVISIONAL"
    assert cand["promotion_stage"] == "REVIEW_READY"
    assert cand["cannot_become_policy"] is True
    assert cand["policy_effect"] is False
    assert cand["role"] == "SUPPORTING_CONTEXT"


def test_case_summaries_carry_the_a_context_banner():
    from scripts.lib.cio_command_center import build_office_home

    home = build_office_home(operator_product={})
    cs = home["case_summaries"]
    assert cs["class"] == "A"
    assert "NON_AUTHORITATIVE" in cs["banner"]


# ── 308: coverage skips CUSIP and CASH ───────────────────────────────────────

def test_thesis_coverage_skips_cusip_and_cash():
    from scripts.lib.cio_investment_product import collect_holdings_thesis_coverage

    cov = collect_holdings_thesis_coverage(holdings=HOLDINGS, root=None)
    symbols = {i["symbol"] for i in cov["items"]}
    assert "CASH" not in symbols
    assert "12507E201" not in symbols
    assert "SCHG" not in symbols            # dust, excluded from held_n
    assert symbols == {"SCHD"}
    assert cov["instrument_id_n"] == 1      # reported separately, not as a ticker
    assert cov["dust_tickers"] == ["SCHG"]


@pytest.mark.parametrize("sym", ["CASH", "12507E201", "543354104"])
def test_non_tickers_are_never_in_the_held_universe(sym):
    from scripts.lib.cio_investment_product import held_equity_symbols

    assert sym not in held_equity_symbols(HOLDINGS)
