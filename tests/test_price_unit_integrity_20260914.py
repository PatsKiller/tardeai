"""Garbage in, garbage out: prices, previous closes, Finviz columns and units.

Measured 2026-09-14 (litmus against Yahoo Finance and the live Finviz header):

* repricer wrote XLI 7.51 / SCHG 8.03 as closes: a sub-one-share position's
  broker ``price`` is its position value; XLI sector RS read -94.9;
* Alpaca ``prev_close`` was two sessions back before today's first bar (HPE
  55.23 vs a Friday close of 62.09, day change +12.4% for a stock not trading);
* portfolio_technical read Finviz exports by column position with a naive
  comma split, after two hand "COL-FIX" edits;
* Finviz Market Cap is MILLIONS and Average Volume THOUSANDS, stored as
  ``market_cap_b`` / ``avg_vol_m``: core_index's $50B floor admitted $50M names,
  the dividend policy scored anything over $2M "institutional", and
  social_awareness inflated volume 1,000-fold (1,000,000-fold for volume_base).

Offline: no network, no database.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402

from lib import finviz_csv as fc  # noqa: E402


def _load(relpath: str):
    """Load THIS tree's copy by path: other suites put another tree's scripts/ on
    sys.path first, and a cached module of the same name would be tested instead."""
    name = "pui_" + relpath.replace("/", "_").removesuffix(".py")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

COVERS = [
    "scripts/lib/finviz_csv.py",
    "scripts/portfolio_repricer.py",
    "scripts/external_market_data_ingest.py",
    "scripts/multi_strategy_classifier.py",
    "scripts/dividend_income_scoring_policy.py",
    "scripts/lib/social_awareness.py",
]

V152 = ('No.,Ticker,Company,Sector,Industry,Country,Market Cap,P/E,Shares Float,Gap,'
        'Average Volume,Relative Volume,Price,Change,Volume\r\n'
        '1,"BRKL","Brookline Bancorp, Inc.","Financial","Banks - Regional","USA",'
        '2201.5,12.1,88.2,-0.40%,812.33,0.91,24.74,-1.10%,701220\r\n'
        '2,"HPE","Hewlett Packard Enterprise Co","Technology","Communication Equipment","USA",'
        '74722.99,29.35,1321.79,-10.44%,21374.39,2.91,56.29,-9.34%,6132257\r\n')


# ── Finviz CSV ───────────────────────────────────────────────────────────────

def test_quoted_comma_in_company_name_does_not_shift_columns():
    rows = fc.parse_export(V152, view=152)
    brkl = next(r for r in rows if r["Ticker"] == "BRKL")
    assert brkl["Company"] == "Brookline Bancorp, Inc." and fc.to_number(brkl["Price"]) == 24.74
    # the positional reader this replaces: parts[12] after a naive split
    naive = V152.split("\r\n")[1].split(",")
    assert naive[12].strip('"') != "24.74"


def test_a_changed_view_raises_instead_of_mapping_garbage():
    moved = V152.replace("Relative Volume", "Volatility (Month)")
    with pytest.raises(fc.FinvizContractError, match="Relative Volume"):
        fc.parse_export(moved, view=152)


def test_units_are_explicit():
    hpe = next(r for r in fc.parse_export(V152, view=152) if r["Ticker"] == "HPE")
    u = fc.normalise_units(hpe)
    assert u["market_cap_usd"] == pytest.approx(74_722.99e6)
    assert u["avg_volume_shares"] == pytest.approx(21_374_390)
    assert u["float_shares"] == pytest.approx(1_321.79e6)
    assert fc.to_number("-9.34%") == -9.34 and fc.to_number("-") is None and fc.to_number("1.2B") == 1.2e9


def test_enrichment_legacy_fields_are_read_in_their_real_units():
    aapl = {"market_cap_b": 4842453.75, "avg_vol_m": 53806.13}
    assert fc.enrichment_market_cap_billions(aapl) == pytest.approx(4842.45375)
    assert fc.enrichment_avg_volume_shares(aapl) == pytest.approx(53_806_130)
    assert fc.enrichment_market_cap_billions({"market_cap_usd": 5e9, "market_cap_b": 1}) == 5.0


# ── repricer close ───────────────────────────────────────────────────────────

def test_fractional_position_value_is_never_written_as_a_close():
    pr = _load("scripts/portfolio_repricer.py")
    schg = {"symbol": "SCHG", "shares": 0.2294, "price": 8.03, "market_value": 8.03}
    assert pr.close_price_for_holding(schg, 35.16) == pytest.approx(8.03 / 0.2294)
    xli = {"symbol": "XLI", "shares": 0.0442, "price": 7.48, "market_value": 7.48,
           "canonical_mark": 172.37, "canonical_mark_type": "last"}
    assert pr.close_price_for_holding(xli, 170.0) == 172.37


def test_close_far_from_the_live_quote_is_refused():
    pr = _load("scripts/portfolio_repricer.py")
    bad = {"symbol": "XLI", "shares": 1.0, "price": 7.51, "market_value": 7.51}
    assert pr.close_price_for_holding(bad, 172.37) is None
    good = {"symbol": "WMT", "shares": 100.0, "price": 108.2, "market_value": 10820.0}
    assert pr.close_price_for_holding(good, 107.9) == pytest.approx(108.2)


# ── Alpaca previous close ────────────────────────────────────────────────────

def _bar(day, close):
    return {"t": f"{day}T04:00:00Z", "c": close}


def test_prev_close_before_todays_first_bar_is_the_last_session_close(monkeypatch):
    ing = _load("scripts/external_market_data_ingest.py")
    today = datetime.now(ZoneInfo("America/New_York")).date()
    last = (today - timedelta(days=3)).isoformat()
    before = (today - timedelta(days=4)).isoformat()
    snap = {"dailyBar": _bar(last, 62.09), "prevDailyBar": _bar(before, 55.23)}
    assert ing._alpaca_prev_close(snap) == 62.09


def test_prev_close_during_the_session_is_the_prior_bar():
    ing = _load("scripts/external_market_data_ingest.py")
    today = datetime.now(ZoneInfo("America/New_York")).date()
    snap = {"dailyBar": _bar(today.isoformat(), 56.29),
            "prevDailyBar": _bar((today - timedelta(days=3)).isoformat(), 62.09)}
    assert ing._alpaca_prev_close(snap) == 62.09


# ── consumers ────────────────────────────────────────────────────────────────

def test_classifier_converts_enrichment_market_cap_to_billions():
    msc = _load("scripts/multi_strategy_classifier.py")
    merged = msc.merge_scan_with_enrichment({"symbol": "AXTI"}, {"AXTI": {"market_cap_b": 4247.18}})
    assert merged["market_cap_b"] == pytest.approx(4.24718)
    ok, _match, reject = msc.match_filters(merged, {"min_market_cap_b": 50})
    assert not ok and any("cap" in r for r in reject)
    own = msc.merge_scan_with_enrichment({"symbol": "AXTI", "market_cap_b": 4.2}, {"AXTI": {"market_cap_b": 4247.18}})
    assert own["market_cap_b"] == 4.2


def test_dividend_policy_reads_real_cap_and_liquidity(monkeypatch):
    dp = _load("scripts/dividend_income_scoring_policy.py")
    tiny = {"symbol": "TINY", "enrichment": {"market_cap_b": 150.0, "avg_vol_m": 40.0,
                                            "div_yield_pct": 6.0, "pe": 12}}
    out = dp.score_dividend_income_candidate(tiny)
    text = " ".join(map(str, out.get("passed") or []))
    assert "institutional" not in text and "(liquid)" not in text


def test_social_awareness_volume_is_not_inflated():
    sa = _load("scripts/lib/social_awareness.py")
    row: dict = {}
    sa._merge_enrichment_cache(row, {"avg_vol_m": 21374.39})
    assert float(row["volume"]) == pytest.approx(21_374_390)
    row2: dict = {}
    sa._merge_enrichment_cache(row2, {"volume_base": 6_132_257})
    assert float(row2["volume"]) == pytest.approx(6_132_257)
