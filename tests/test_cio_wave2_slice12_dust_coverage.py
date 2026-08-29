"""Wave 2 slice 12 / 12a / 12b / 12c — holdings truth.

12   CUSIP-only held rows are ``instrument_id``, never a ticker.
12a  DUST_RESIDUAL (aggregate market value < $50/ticker) leaves held_n.
12b  coverage.with_plan counts open S1/S3/S5/S6 against the open-plan store,
     not the 12-row /v3/cio/home UI window.
12c  observational S1 skips dust as well as CUSIP/CASH and open-S1 symbols.

READ_ONLY_ADVISORY. No lot is deleted; dust is a label.
"""
from __future__ import annotations

import pytest

from scripts.lib import holdings_universe as hu
from scripts.lib.cio_command_center import build_office_coverage, build_office_home
from scripts.lib.cio_investment_product import (
    collect_held_instrument_ids,
    collect_holdings_thesis_coverage,
    dust_symbols,
    held_equity_symbols,
    held_equity_symbols_nondust,
    market_value_by_symbol,
)
from scripts.lib.cio_observational_s1 import collect_held_without_open_s1


def _row(symbol, mv, account="schwab_taxable", **kw):
    row = {"symbol": symbol, "account": account, "asset_type": "equity", "shares": 1.0}
    if mv is not None:
        row["market_value"] = mv
    row.update(kw)
    return row


# Mirrors the live book: SCHG $8.09 dust, SCHD a real hold, one CUSIP, one cash.
LIVE_SHAPED = {
    "holdings": [
        {"symbol": "CASH", "is_cash": True, "asset_type": "cash", "market_value": 585917.80},
        _row("12507E201", 0.0, name="DELISTED — CUSIP 12507E201"),
        _row("SCHG", 8.09, shares=0.2294),
        _row("SRNE", 0.90),
        _row("SCHD", 365694.75),
        _row("BAH", 673.83),
    ]
}


# ── 12a: dust policy ─────────────────────────────────────────────────────────

def test_dust_policy_is_documented_and_value_based():
    assert hu.DUST_MAX_MARKET_VALUE_USD == 50.0
    assert hu.DUST_POLICY["basis"] == "market_value"
    assert hu.DUST_POLICY["aggregation"] == "per_ticker_across_accounts"
    assert hu.DUST_POLICY["deletes_lots"] is False
    assert "0.5%" in hu.DUST_POLICY["rejected_alternative"]


def test_schg_is_dust_and_schd_is_not():
    assert dust_symbols(LIVE_SHAPED) == ["SCHG", "SRNE"]
    assert "SCHG" not in held_equity_symbols_nondust(LIVE_SHAPED)
    assert "SCHD" in held_equity_symbols_nondust(LIVE_SHAPED)
    # The lot is still visible in the raw universe — label, not deletion.
    assert "SCHG" in held_equity_symbols(LIVE_SHAPED)


def test_dust_is_aggregated_across_accounts_not_per_row():
    """A name held tiny in one account and large in another is not dust."""
    holdings = {"holdings": [
        _row("SPCX", 5.00, account="schwab_taxable"),
        _row("SPCX", 21833.60, account="schwab_rollover_ira"),
    ]}
    assert market_value_by_symbol(holdings)["SPCX"] == 21838.60
    assert dust_symbols(holdings) == []


def test_unknown_market_value_is_never_dust():
    """A missing price must not silently drop a position from coverage."""
    holdings = {"holdings": [_row("ZZZX", None)]}
    assert market_value_by_symbol(holdings) == {"ZZZX": None}
    assert dust_symbols(holdings) == []
    assert "ZZZX" in held_equity_symbols_nondust(holdings)


def test_one_unknown_leg_makes_the_whole_ticker_unknown():
    holdings = {"holdings": [
        _row("ZZZX", 10.0, account="a"),
        _row("ZZZX", None, account="b"),
    ]}
    assert market_value_by_symbol(holdings)["ZZZX"] is None
    assert dust_symbols(holdings) == []


def test_boundary_exactly_at_threshold_is_held():
    assert hu.is_dust_market_value(49.99) is True
    assert hu.is_dust_market_value(50.0) is False
    assert hu.is_dust_market_value(None) is False


def test_coverage_excludes_dust_from_held_n_but_still_reports_it():
    cov = collect_holdings_thesis_coverage(holdings=LIVE_SHAPED, root=None)
    assert cov["held_n"] == 2                              # SCHD + BAH
    assert sorted(i["symbol"] for i in cov["items"]) == ["BAH", "SCHD"]
    assert cov["dust_tickers"] == ["SCHG", "SRNE"]
    assert cov["dust_n"] == 2
    assert cov["held_n_including_dust"] == cov["held_n"] + cov["dust_n"]
    assert all(i["thesis_status"] == "NOT_REQUIRED" for i in cov["dust_items"])
    assert cov["no_fake_thesis"] is True


# ── 12: instrument_id, not ticker ────────────────────────────────────────────

def test_cusip_rows_are_instrument_ids_never_tickers():
    ids = collect_held_instrument_ids(LIVE_SHAPED)
    assert ids["instrument_id_n"] == 1
    item = ids["items"][0]
    assert item["instrument_id"] == "12507E201"
    assert item["id_type"] == "CUSIP"
    assert item["is_ticker"] is False
    assert item["ticker"] is None
    # and it is not in the ticker universe
    assert "12507E201" not in held_equity_symbols(LIVE_SHAPED)


@pytest.mark.parametrize("raw,expected", [
    ("12507E201", "CUSIP"),
    ("543354104", "CUSIP"),
    ("628518102", "CUSIP"),
    ("US0378331005", "ISIN"),
])
def test_instrument_id_classification(raw, expected):
    assert hu.classify_instrument_id(raw) == expected


def test_coverage_carries_instrument_ids_and_never_mints_thesis_for_them():
    cov = collect_holdings_thesis_coverage(holdings=LIVE_SHAPED, root=None)
    assert cov["instrument_id_n"] == 1
    assert cov["instrument_ids"][0]["instrument_id"] == "12507E201"
    assert "12507E201" not in [i["symbol"] for i in cov["items"]]
    assert "12507E201" not in cov["dust_tickers"]


def test_cash_is_not_an_instrument_id():
    assert collect_held_instrument_ids(LIVE_SHAPED)["items"][0]["instrument_id"] != "CASH"


# ── 12b: the with_plan counter ───────────────────────────────────────────────

HTC = {
    "held_n": 2,
    "current_n": 2,
    "items": [{"symbol": "SCHD"}, {"symbol": "BAH"}, {"symbol": "SCHG"}],
    "dust_tickers": ["SCHG"],
}


def _plan(sit, syms, **kw):
    row = {"situation_type": sit, "symbols": syms, "status": "draft"}
    row.update(kw)
    return row


def test_with_plan_counts_the_whole_store_not_the_home_window():
    window = [_plan("S1_POSITION_LIFECYCLE", ["SCHD"])]
    store = [
        _plan("S1_POSITION_LIFECYCLE", ["SCHD"]),
        _plan("S6_CONCENTRATION_OR_DISPOSITION", ["BAH"]),
    ]
    windowed = build_office_coverage(holdings_thesis_coverage=HTC, plans=window)
    full = build_office_coverage(holdings_thesis_coverage=HTC, plans=window, coverage_plans=store)
    assert windowed["with_plan"] == 1
    assert windowed["with_plan_source"] == "home_plan_window"
    assert full["with_plan"] == 2
    assert full["with_plan_symbols"] == ["BAH", "SCHD"]
    assert full["with_plan_source"] == "open_plan_store"


def test_with_plan_ignores_s0_and_s7_situation_types():
    store = [
        _plan("S0_OPERATOR_CONVERSE", ["SCHD"]),
        _plan("S7_WATCH_PROMOTION", ["BAH"]),
    ]
    cov = build_office_coverage(holdings_thesis_coverage=HTC, coverage_plans=store)
    assert cov["with_plan"] == 0
    assert cov["open_plans_considered"] == 0


def test_with_plan_ignores_closed_plans():
    store = [_plan("S1_POSITION_LIFECYCLE", ["SCHD"], status="cancelled")]
    cov = build_office_coverage(holdings_thesis_coverage=HTC, coverage_plans=store)
    assert cov["with_plan"] == 0


def test_dust_symbol_never_counts_as_covered():
    store = [_plan("S1_POSITION_LIFECYCLE", ["SCHG"])]
    cov = build_office_coverage(holdings_thesis_coverage=HTC, coverage_plans=store)
    assert cov["with_plan"] == 0
    assert "SCHG" not in cov["with_plan_symbols"]


def test_with_research_needs_hermes_result_id_not_just_a_plan():
    store = [
        _plan("S1_POSITION_LIFECYCLE", ["SCHD"], hermes_result_id="res_1"),
        _plan("S1_POSITION_LIFECYCLE", ["BAH"]),
    ]
    cov = build_office_coverage(holdings_thesis_coverage=HTC, coverage_plans=store)
    assert cov["with_plan"] == 2
    assert cov["with_research"] == 1


def test_home_threads_coverage_plans_through():
    home = build_office_home(
        operator_product={"holdings_thesis_coverage": HTC},
        plans=[],
        coverage_plans=[_plan("S1_POSITION_LIFECYCLE", ["SCHD", "BAH"])],
    )
    assert home["coverage"]["with_plan"] == 2
    assert home["coverage"]["with_plan_source"] == "open_plan_store"
    assert home["telegram_sent"] is False


# ── 12c: observational S1 skips dust ─────────────────────────────────────────

class _Store:
    def __init__(self, open_plans):
        self._rows = open_plans

    def list_open_plans(self, *, situation_type=None, limit=400):
        return [p for p in self._rows if not situation_type or p["situation_type"] == situation_type]


def test_observational_s1_skips_dust_cusip_and_cash():
    dry = collect_held_without_open_s1(holdings=LIVE_SHAPED, plans=_Store([]), cap=5)
    assert dry["would_n"] == 2
    assert sorted(r["symbol"] for r in dry["would"]) == ["BAH", "SCHD"]
    assert dry["skipped_dust"] == ["SCHG", "SRNE"]
    assert dry["held_n"] == 2
    assert dry["held_n_including_dust"] == 4
    assert dry["notify"] is False
    assert dry["financial_action"] is False


def test_observational_s1_still_skips_symbols_with_an_open_s1():
    store = _Store([{"situation_type": "S1_POSITION_LIFECYCLE", "symbols": ["SCHD"]}])
    dry = collect_held_without_open_s1(holdings=LIVE_SHAPED, plans=store, cap=5)
    assert dry["skipped_open_s1"] == ["SCHD"]
    assert [r["symbol"] for r in dry["would"]] == ["BAH"]


def test_observational_s1_never_mints_for_dust_even_when_uncovered():
    holdings = {"holdings": [_row("SCHG", 8.09, shares=0.2294)]}
    dry = collect_held_without_open_s1(holdings=holdings, plans=_Store([]), cap=5)
    assert dry["would_n"] == 0
    assert dry["skipped_dust"] == ["SCHG"]


# ── card honesty ─────────────────────────────────────────────────────────────

def test_coverage_card_help_text_states_the_dust_rule():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "apps/command-center-v3/src/pages/CioHub.tsx"
    ).read_text(encoding="utf-8")
    assert "excluded from held_n" in src
    assert "S1/S3/S5/S6" in src
    # the stale claim that dust still counts must be gone
    assert "SCHG dust may still count in held_n" not in src
