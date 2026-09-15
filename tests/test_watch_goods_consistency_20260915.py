"""2026-09-15: every tracked name carries the same goods across the watchlist and proposals."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _m():
    spec = importlib.util.spec_from_file_location("goods_t", ROOT / "scripts" / "watch_goods_consistency_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FULL = {
    "price_fresh": True, "entry_plan_7d": True, "cio_decision_7d": True, "catalyst_30d": True, "quality": "ADMITTED",
    "profile": {"sector": "Industrials", "industry": "Aerospace & Defense", "next_earnings_date": "2026-10-20"},
    "card": {"ideal_entry": 190.0, "stop_loss": 180.0, "target_price": 215.0, "catalyst_summary": "Contract win: …"},
    "enrichment": {"sector": "Industrials", "industry": "Aerospace & Defense", "market_cap_b": 263271.08, "float_m": 1300.0, "rvol": 1.1},
}


def test_all_goods_present():
    g = _m().goods_for("RTX", FULL)
    assert set(g) == set(_m().GOODS) and all(g.values())


def test_missing_goods_are_reported():
    src = {"profile": {}, "card": {"ideal_entry": 1.0}, "enrichment": {}}
    g = _m().goods_for("X", src)
    assert not any(g.values())


def test_enrichment_fills_sector_when_profile_missing():
    src = dict(FULL, profile={})
    g = _m().goods_for("RTX", src)
    assert g["sector"] and g["industry"] and not g["earnings_date"]


def test_proposal_mismatch_and_lag_detection():
    m = _m().proposal_mismatches({"sector": "Technology", "industry": None, "float_m": None, "rvol": 2.0, "catalyst": ""}, FULL)
    assert "sector differs (Technology vs Industrials)" in m
    assert "industry missing on proposal" in m and "float_m missing on proposal" in m
    assert "catalyst missing on proposal" in m and not any("rvol" in x for x in m)


def test_consistent_proposal_has_no_mismatch():
    p = {"sector": "industrials", "industry": "Aerospace & Defense", "float_m": 1300.0, "rvol": 1.1, "catalyst": "contract"}
    assert _m().proposal_mismatches(p, FULL) == []


def test_summarize_counts_and_percentages():
    mod = _m()
    src = {"RTX": dict(FULL, on_watchlist=True), "ZZZ": {"on_watchlist": True, "profile": {}, "card": {}, "enrichment": {}}}
    rep = mod.summarize(src, [{"id": 1, "symbol": "RTX", "sector": "Industrials", "industry": "Aerospace & Defense",
                               "float_m": 1.0, "rvol": 1.0, "catalyst": "x"}])
    assert rep["watchlist_symbols"] == 2 and rep["coverage"]["sector"] == 1 and rep["coverage_pct"]["sector"] == 50.0
    assert rep["symbols_missing_any"] == 1 and rep["proposals_with_mismatch"] == 0


def test_backfill_only_fills_empty_fields_and_is_opt_in():
    src = (ROOT / "scripts" / "watch_goods_consistency_check.py").read_text(encoding="utf-8")
    assert "COALESCE({k}, %s)" in src and 'ap.add_argument("--apply-proposal-backfill"' in src
    assert "conn.rollback()" in src


def test_sector_aliases_between_yahoo_and_finviz_are_not_mismatches():
    src = dict(FULL, profile={"sector": "Financial Services", "industry": "Capital Markets"}, enrichment={"sector": "Financial"})
    p = {"sector": "Financial", "industry": "Capital Markets", "float_m": None, "rvol": None, "catalyst": "x"}
    assert not any("sector differs" in m for m in _m().proposal_mismatches(p, src))
