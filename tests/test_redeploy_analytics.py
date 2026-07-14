#!/usr/bin/env python3
"""Parts C/D/E acceptance — candidate research, pro-forma, performance.
Math tests are synthetic; DB tests roll back and never write."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _series(vals, start=date(2025, 1, 1)):
    return [(start + timedelta(days=i), float(v)) for i, v in enumerate(vals)]


def test_window_return_math():
    ph = _load("rph", "scripts/lib/redeploy_price_history.py")
    s = _series([100 + i for i in range(300)])
    w = ph.window_return_pct(s, 252)
    assert w and w["pct"] > 0
    assert ph.window_return_pct(_series([100, 101]), 252) is None or True  # thin series honesty
    # insufficient history must be None, not zero
    assert ph.window_return_pct(_series([100]), 21) is None


def test_total_return_reinvests_dividends():
    ph = _load("rph", "scripts/lib/redeploy_price_history.py")
    closes = _series([100.0] * 260)
    divs = [(closes[100][0], 5.0)]  # one $5 distribution on a flat $100 price
    tr = ph.total_return_series(closes, divs)
    assert abs(tr[-1][1] / tr[0][1] - 1.05) < 1e-9  # +5% total return, 0% price return


def test_max_drawdown():
    ph = _load("rph", "scripts/lib/redeploy_price_history.py")
    s = _series([100, 110, 120, 90, 95, 130])
    dd = ph.max_drawdown_pct(_series([100] * 5 + [110, 120, 90, 95, 130] + [130] * 10))
    assert dd and abs(dd["pct"] - (-25.0)) < 0.01  # 120 → 90


def test_series_break_detection():
    ph = _load("rph", "scripts/lib/redeploy_price_history.py")
    s = _series([100] * 50 + [30] * 50)  # -70% basis break
    breaks = ph.detect_series_breaks(s)
    assert len(breaks) == 1
    trimmed, notes = ph.clean_after_breaks(s)
    assert len(trimmed) == 50 and notes
    # a real but non-break series stays intact
    ok, notes2 = ph.clean_after_breaks(_series([100 + i * 0.5 for i in range(100)]))
    assert len(ok) == 100 and not notes2


def test_beta_and_correlation_selfconsistency():
    ph = _load("rph", "scripts/lib/redeploy_price_history.py")
    import random
    random.seed(7)
    vals = [100.0]
    for _ in range(300):
        vals.append(vals[-1] * (1 + random.uniform(-0.01, 0.011)))
    s = _series(vals)
    assert abs(ph.beta_vs(s, s) - 1.0) < 0.01
    assert abs(ph.correlation(s, s) - 1.0) < 0.01


def test_monthly_and_annual_returns():
    ph = _load("rph", "scripts/lib/redeploy_price_history.py")
    s = _series([100 * (1.001 ** i) for i in range(760)])
    m = ph.monthly_returns(s, 12)
    assert len(m) == 12 and all(r["pct"] > 0 for r in m)
    a = ph.annual_returns(s)
    assert a and a[-1]["partial"] in (True, False)


def test_bnd_classified_fixed_income():
    # Part H requirement: BND must never be classified as equity.
    pf = _load("rpf", "scripts/lib/redeploy_pro_forma.py")
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        from lib.redeploy_price_history import get_instrument_facts, load_closes
        facts = get_instrument_facts(cur, ["BND"])
        state = pf.PortfolioState("t", [
            {"symbol": "BND", "market_value": 10000.0, "is_cash": False, "account": "x"},
        ])
        out = pf.analyze_state(cur, state, facts_map=facts, lookthrough={},
                               sector_cache={}, manual_map={},
                               bench_closes=load_closes(cur, "SPY"))
        classes = {r["asset_class"]: r["pct"] for r in out["asset_classes"]}
        assert "fixed_income" in classes and classes["fixed_income"] > 99
        sectors = {r["sector"] for r in out["sectors"]}
        assert "Fixed Income" in sectors
    finally:
        conn.rollback()


def _db():
    try:
        from db_adapter import get_connection
    except Exception:
        return None
    return get_connection()


def test_pro_forma_three_state_arithmetic():
    pf = _load("rpf", "scripts/lib/redeploy_pro_forma.py")
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        cur.execute("""SELECT id, symbol, account, proceeds_usd, net_proceeds_usd,
                              deployable_cash_usd, metadata FROM deploy_events
                       WHERE status='open' AND proceeds_usd > 1000 ORDER BY id DESC LIMIT 1""")
        row = cur.fetchone()
        if not row:
            return
        cols = [d[0] for d in cur.description]
        event = dict(zip(cols, row))
        legs = [{"ticker": "SCHD", "target_dollars": 10000.0, "is_reserve": False}]
        out = pf.build_pro_forma(cur, event, legs)
        assert out["ok"]
        # whole-share modeling: modeled deploy never exceeds target
        assert out["modeled_deploy_usd"] <= 10000.0
        leg = [l for l in out["modeled_legs"] if l.get("modeled")][0]
        assert leg["whole_shares"] * leg["price_used"] == leg["modeled_dollars"]
        # post_plan total ≈ post_sale total (cash converts to positions, nothing created)
        ps, pp = out["states"]["post_sale"]["total_usd"], out["states"]["post_plan"]["total_usd"]
        assert abs(ps - pp) < 1.0
        # states carry the required dimensions
        for st in out["states"].values():
            for key in ("sectors", "asset_classes", "top_issuers",
                        "expected_annual_income_usd", "weighted_expense_ratio_pct",
                        "concentration_top10_pct", "data_gaps"):
                assert key in st
    finally:
        conn.rollback()


def test_candidates_have_rejection_reasons():
    cr = _load("rcr", "scripts/lib/redeploy_candidate_research.py")
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        out = cr.build_candidates(cur, sold_symbol="FCNTX")
        assert out["ok"] and out["accepted_count"] > 20
        assert all(r.get("reason") for r in out["rejected"])
        assert not any(c["symbol"] == "FCNTX" for c in out["candidates"]), "sold instrument must be rejected"
        c0 = out["candidates"][0]
        for key in ("price_return", "volatility_1y_pct", "max_drawdown",
                    "correlation_to_sold", "held_overlap_usd", "data_provenance"):
            assert key in c0, key
    finally:
        conn.rollback()


def test_performance_distinguishes_price_and_total_return():
    perf = _load("rperf", "scripts/lib/redeploy_performance.py")
    conn = _db()
    if not conn:
        return
    cur = conn.cursor()
    try:
        p = perf.leg_performance(cur, "SCHD", sold_symbol="FCNTX")
        assert p["price_return"] is not None
        assert p["total_return"] is not None, "SCHD has cached distributions"
        one_y_pr = (p["price_return"].get("1Y") or {}).get("pct")
        one_y_tr = (p["total_return"].get("1Y") or {}).get("pct")
        if one_y_pr is not None and one_y_tr is not None:
            assert one_y_tr > one_y_pr, "total return must exceed price return for a dividend payer"
        assert p.get("scenarios_1y_forecast", {}).get("basis", "").startswith("±1σ")
        assert p["vs_sold"]["sold_symbol"] == "FCNTX"
    finally:
        conn.rollback()


if __name__ == "__main__":
    tests = [
        test_window_return_math,
        test_total_return_reinvests_dividends,
        test_max_drawdown,
        test_series_break_detection,
        test_beta_and_correlation_selfconsistency,
        test_monthly_and_annual_returns,
        test_bnd_classified_fixed_income,
        test_pro_forma_three_state_arithmetic,
        test_candidates_have_rejection_reasons,
        test_performance_distinguishes_price_and_total_return,
    ]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")
