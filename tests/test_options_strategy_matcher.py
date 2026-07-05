#!/usr/bin/env python3
"""MULTI-STRATEGY OPTIONS Stage 1 — strategy matcher (operator spec Part C).

Covers: run_matchers API shape, thesis gating both sides (bullish for atm_call,
bearish for atm_put — watchlist verdicts, held-with-positive-thesis, explicit
bearish thesis, hedge-of-held), deep_itm_call delegation to the existing
generator (pass / watch / fail), watch status on disclosed-flag-only issues,
the not_applicable set with honest reasons (covered_call / cash_secured_put /
protective_put / credit_spread), cross_strategy_summary shape, in-strategy
ranking, and the pure-library guarantee (no queue writes, no broker imports).

    .venv/bin/python -m pytest tests/test_options_strategy_matcher.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import strategy_matcher as sm  # noqa: E402

SPOT = 100.0
NO_IV = {"available": False, "reason": "iv context not computed (test)"}
NO_EARNINGS = "2099-01-01"


# ── chain snapshot fixture (parse_chain shape) for the ATM lane ───────────────

def _contract(side="call", strike=100.0, mid=4.0, *, delta=0.52, oi=800,
              volume=50, spread_pct=3.0, dte=33, liquidity_score=75):
    return {"side": side, "strike": strike, "bid": mid - 0.1, "ask": mid + 0.1,
            "mid": mid, "spread_pct": spread_pct, "volume": volume, "oi": oi,
            "delta": delta, "iv": 30.0, "dte": dte,
            "liquidity_score": liquidity_score}


def _snapshot():
    return {"available": True, "symbol": "TEST", "underlying_price": SPOT,
            "expirations": [
                {"exp": "2026-08-07", "dte": 33,
                 "contracts": [_contract(), _contract(side="put", delta=-0.52),
                               _contract(strike=99.0, liquidity_score=60),
                               _contract(side="put", strike=99.0, delta=-0.48,
                                         liquidity_score=60)]},
                {"exp": "2026-09-04", "dte": 61,
                 "contracts": [_contract(strike=101.0, dte=61),
                               _contract(side="put", strike=101.0, delta=-0.55,
                                         dte=61)]},
            ],
            "liquidity_score": 70}


# ── deep-ITM analysis fixture (deep_itm_call_analysis shape) ─────────────────

DEEP_SPOT = 200.0


def _deep_candidate(earnings_before=False):
    strike, mid = 150.0, 55.0
    return {
        "strike": strike, "exp": "2026-10-16", "dte": 89,
        "bid": mid - 0.5, "ask": mid + 0.5, "mid": mid,
        "delta": 0.88, "iv": 0.30, "volume": 20, "oi": 500,
        "spread_pct": 2.0, "liquidity_score": 70,
        "flags": {"wide_spread": False, "low_oi": False, "no_volume": False,
                  "no_quote": False, "earnings_before_expiry": earnings_before},
        "intrinsic_value": DEEP_SPOT - strike,
        "extrinsic_value": round(mid - (DEEP_SPOT - strike), 4),
        "breakeven": strike + mid,
        "breakeven_move_pct": round(((strike + mid) / DEEP_SPOT - 1) * 100, 2),
        "max_loss": mid * 100, "capital_required": mid * 100,
        "capital_vs_100_shares": {"contract_debit": mid * 100,
                                  "100_shares": DEEP_SPOT * 100,
                                  "capital_ratio_pct": 27.5},
    }


def _deep_analysis(sym, earnings_before=False):
    return {
        "strategy": "deep_itm_call", "symbol": sym, "available": True,
        "educational_only": True, "banner": "EDUCATIONAL_ONLY — test fixture",
        "source": "fixture", "generated_at": "2026-07-05T00:00:00+00:00",
        "underlying_price": DEEP_SPOT, "delta_range": [0.80, 0.95],
        "selection_modes_used": ["delta"],
        "next_earnings_date": "2026-09-01" if earnings_before else None,
        "dte_buckets": [{"target_dte": 90, "exp": "2026-10-16", "dte": 89,
                         "selection_mode": "delta", "available": True,
                         "selected": _deep_candidate(earnings_before),
                         "candidates": [_deep_candidate(earnings_before)]}],
        "chain_liquidity_score": 70,
        "feasibility": {"feasible": True, "score": 80, "reason": "fixture"},
        "iv_context": NO_IV,
    }


def _deep_degraded(us, cfg=None, **kw):
    return {"proposals": [],
            "per_underlying": [{"symbol": us[0]["symbol"], "status": "degraded",
                                "reason": "weekend — no chain"}]}


def _run(context, **kw):
    kw.setdefault("snapshot", _snapshot())
    kw.setdefault("earnings_date", NO_EARNINGS)
    kw.setdefault("iv_context", NO_IV)
    if "deep_itm_analysis_fn" not in kw and "deep_itm_fn" not in kw:
        kw["deep_itm_fn"] = _deep_degraded
    return sm.run_matchers("NVDA", context, **kw)


BULLISH = {"verdict": "strong_buy", "held_shares": None}
BEARISH = {"verdict": "sell", "held_shares": None}


# ── (1) API shape + statuses ─────────────────────────────────────────────────

def test_result_shape_and_status_vocabulary():
    res = _run(BULLISH)
    assert res["symbol"] == "NVDA"
    assert set(res) >= {"symbol", "generated_at", "context",
                        "strategy_results", "cross_strategy_summary"}
    results = res["strategy_results"]
    # every registry strategy is reported (7 rows after the Stage 1 extension)
    assert set(results) == {"deep_itm_call", "covered_call", "cash_secured_put",
                            "protective_put", "credit_spread",
                            "atm_call", "atm_put"}
    for sid, r in results.items():
        assert r["status"] in sm.ALL_STATUSES, sid
        assert r["reason"], sid
        assert isinstance(r["proposals"], list), sid


def test_explicit_strategy_list_and_unknown_id():
    res = _run(BULLISH, strategies=["atm_call", "iron_condor"])
    results = res["strategy_results"]
    assert set(results) == {"atm_call", "iron_condor"}
    assert results["iron_condor"]["status"] == "not_applicable"
    assert "not in options_strategy_registry" in results["iron_condor"]["reason"]


# ── (2) thesis gating — both sides ───────────────────────────────────────────

def test_bullish_context_passes_call_fails_put():
    res = _run(BULLISH)["strategy_results"]
    assert res["atm_call"]["status"] == "pass"
    assert len(res["atm_call"]["proposals"]) >= 1
    assert res["atm_put"]["status"] == "fail"
    assert "bearish thesis missing" in res["atm_put"]["reason"]
    assert res["atm_put"]["proposals"] == []


def test_bearish_context_passes_put_fails_call():
    res = _run(BEARISH)["strategy_results"]
    assert res["atm_put"]["status"] == "pass"
    assert len(res["atm_put"]["proposals"]) >= 1
    assert all(p["strategy"] == "atm_put" for p in res["atm_put"]["proposals"])
    assert res["atm_call"]["status"] == "fail"
    assert "bullish thesis missing" in res["atm_call"]["reason"]


@pytest.mark.parametrize("verdict", ["sell", "avoid", "deteriorating", "strong_sell"])
def test_bearish_verdict_spectrum(verdict):
    res = _run({"verdict": verdict, "held_shares": None})["strategy_results"]
    assert res["atm_put"]["status"] == "pass"


def test_held_with_positive_thesis_is_bullish():
    ctx = {"verdict": None, "held_shares": 50.0, "thesis_direction": "bullish"}
    res = _run(ctx)["strategy_results"]
    assert res["atm_call"]["status"] == "pass"
    intel = res["atm_call"]["proposals"][0]["meta"]["underlying_intel"]
    assert intel["conviction_source"] == "held_with_positive_thesis"


def test_held_without_thesis_is_not_bullish():
    ctx = {"verdict": None, "held_shares": 50.0}
    res = _run(ctx)["strategy_results"]
    assert res["atm_call"]["status"] == "fail"
    assert "bullish thesis missing" in res["atm_call"]["reason"]


def test_hedge_of_held_enables_put():
    ctx = {"verdict": None, "held_shares": 100.0, "hedge_of_held": True}
    res = _run(ctx)["strategy_results"]
    assert res["atm_put"]["status"] == "pass"
    intel = res["atm_put"]["proposals"][0]["meta"]["underlying_intel"]
    assert intel["conviction_source"] == "hedge_of_held"
    assert intel["hedge_of_held"] is True


def test_explicit_bearish_thesis_enables_put_without_verdict():
    ctx = {"verdict": None, "held_shares": None, "thesis_direction": "bearish"}
    res = _run(ctx)["strategy_results"]
    assert res["atm_put"]["status"] == "pass"


def test_hold_verdict_is_neither():
    res = _run({"verdict": "hold", "held_shares": None})["strategy_results"]
    assert res["atm_call"]["status"] == "fail"
    assert res["atm_put"]["status"] == "fail"


# ── (3) deep_itm_call delegation ─────────────────────────────────────────────

def test_deep_itm_delegates_pass():
    res = _run(BULLISH,
               deep_itm_analysis_fn=lambda sym, **kw: _deep_analysis(sym))
    r = res["strategy_results"]["deep_itm_call"]
    assert r["status"] == "pass"
    assert r["proposals"][0]["strategy"] == "deep_itm_call"
    assert r["proposals"][0]["enterprise"]["live_eligible"] is False


def test_deep_itm_watch_on_earnings_flag():
    res = _run(BULLISH,
               deep_itm_analysis_fn=lambda sym, **kw: _deep_analysis(
                   sym, earnings_before=True))
    r = res["strategy_results"]["deep_itm_call"]
    assert r["status"] == "watch"
    assert "disclosed flags" in r["reason"]


def test_deep_itm_fail_when_chain_degraded():
    res = _run(BULLISH, deep_itm_fn=_deep_degraded)
    r = res["strategy_results"]["deep_itm_call"]
    assert r["status"] == "fail"
    assert "chain unavailable" in r["reason"]


def test_deep_itm_fail_below_conviction_floor():
    # bearish-only context → bullish conviction 0.0 < deep-ITM floor 0.55
    res = _run(BEARISH,
               deep_itm_analysis_fn=lambda sym, **kw: _deep_analysis(sym))
    r = res["strategy_results"]["deep_itm_call"]
    assert r["status"] == "fail"
    assert "below floor" in r["reason"]


# ── (4) watch status on disclosed-flag-only issues (ATM lane) ────────────────

def test_atm_watch_when_earnings_flagged():
    res = _run(BULLISH, earnings_date="2026-08-01")   # before both fixture expiries
    r = res["strategy_results"]["atm_call"]
    assert r["status"] == "watch"
    assert "disclosed flags" in r["reason"]
    assert all("earnings_before_expiry_flagged" in p["meta"]["gate_flags"]
               for p in r["proposals"])


def test_atm_fail_when_gates_reject_everything():
    thin = {"available": True, "symbol": "TEST", "underlying_price": SPOT,
            "expirations": [{"exp": "2026-08-07", "dte": 33,
                             "contracts": [_contract(oi=50)]}],   # oi < 300
            "liquidity_score": 10}
    res = _run(BULLISH, snapshot=thin)
    r = res["strategy_results"]["atm_call"]
    assert r["status"] == "fail"
    assert "no candidates passed gates" in r["reason"]


def test_atm_fail_when_chain_unavailable():
    res = _run(BULLISH, snapshot={"available": False, "reason": "weekend — no chain"})
    r = res["strategy_results"]["atm_call"]
    assert r["status"] == "fail"
    assert "chain unavailable" in r["reason"] and "weekend" in r["reason"]


# ── (5) not_applicable set — honest reasons, no generation ───────────────────

def test_not_applicable_strategies_and_reasons():
    res = _run(dict(BULLISH, held_shares=None))["strategy_results"]
    for sid in ("covered_call", "cash_secured_put", "protective_put",
                "credit_spread"):
        assert res[sid]["status"] == "not_applicable", sid
        assert res[sid]["proposals"] == [], sid
    assert "requires 100 held shares" in res["covered_call"]["reason"]
    assert "scanner_mode" in res["cash_secured_put"]["reason"]
    assert "requires existing long exposure" in res["protective_put"]["reason"]
    assert "RESEARCH_ONLY" in res["credit_spread"]["reason"]


def test_not_applicable_reasons_acknowledge_held_shares():
    res = _run({"verdict": "buy", "held_shares": 200.0})["strategy_results"]
    assert res["covered_call"]["status"] == "not_applicable"
    assert "held shares present" in res["covered_call"]["reason"]
    assert res["protective_put"]["status"] == "not_applicable"
    assert "hedge generation arrives" in res["protective_put"]["reason"]


# ── (6) cross-strategy summary shape (Part C example) ────────────────────────

def test_cross_strategy_summary_shape_and_counts():
    res = _run(BULLISH, deep_itm_analysis_fn=lambda sym, **kw: _deep_analysis(sym))
    cs = res["cross_strategy_summary"]
    assert set(cs) >= {"symbol", "considered", "counts", "pass", "watch", "fail",
                       "not_applicable", "total_proposals", "best_proposal",
                       "thesis"}
    assert cs["symbol"] == "NVDA"
    assert cs["considered"] == 7
    assert sorted(cs["pass"]) == ["atm_call", "deep_itm_call"]
    assert cs["fail"] == ["atm_put"]
    assert sorted(cs["not_applicable"]) == ["cash_secured_put", "covered_call",
                                            "credit_spread", "protective_put"]
    assert cs["counts"] == {"pass": 2, "watch": 0, "fail": 1, "not_applicable": 4}
    assert cs["total_proposals"] >= 3
    best = cs["best_proposal"]
    assert best is not None
    assert best["strategy"] in ("atm_call", "deep_itm_call")
    # best really is the max edge across all strategies' proposals
    all_scores = [p["edge_score"] for r in res["strategy_results"].values()
                  for p in r["proposals"]]
    assert best["edge_score"] == max(all_scores)
    assert cs["thesis"]["bullish"] is True and cs["thesis"]["bearish"] is False


# ── (7) ranking within a strategy ────────────────────────────────────────────

def test_proposals_ranked_within_strategy():
    res = _run(BULLISH)
    props = res["strategy_results"]["atm_call"]["proposals"]
    scores = [p["edge_score"] for p in props]
    assert scores == sorted(scores, reverse=True)


# ── (8) pure library — no queue writes, no broker surface ────────────────────

def test_matcher_never_writes_to_queue(monkeypatch):
    import options_desk_enterprise as ode
    monkeypatch.setattr(ode, "sync_approval_queue",
                        lambda rows, **kw: pytest.fail("matcher must never write"))
    res = _run(BULLISH, deep_itm_analysis_fn=lambda sym, **kw: _deep_analysis(sym))
    assert res["cross_strategy_summary"]["total_proposals"] >= 1


MATCHER_PATH = ROOT / "scripts" / "lib" / "options_pipeline" / "strategy_matcher.py"
FORBIDDEN_MODULES = {
    "options_order_pilot", "options_pilot_arm", "brokers", "approval_service",
    "schwab_transport", "schwab_pilot_orders", "alpaca_trade_api", "alpaca",
    "trade_executor", "order_executor", "telegram_2fa", "two_factor",
    "options_execution_policy",
    # the matcher additionally never touches the desk queue writer surface
    "options_desk_enterprise",
}


def test_matcher_module_has_no_forbidden_imports_or_queue_calls():
    src = MATCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.update({a.name, a.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.update({node.module, node.module.split(".")[0]})
    assert not mods & FORBIDDEN_MODULES
    # never references the queue-writer surface, even by attribute
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "sync_approval_queue" not in names
    assert "submit_to_desk_queue" not in names


def test_statuses_are_exactly_the_documented_vocabulary():
    assert sm.ALL_STATUSES == ("pass", "watch", "fail", "not_applicable")


# ── (9) context resolution stays honest offline ──────────────────────────────

def test_verdict_normalization():
    assert sm._normalize_verdict("Strong Buy") == "strong_buy"
    assert sm._normalize_verdict("STRONG-SELL") == "strong_sell"
    assert sm._normalize_verdict(None) is None
    assert sm.thesis_of({"verdict": "Strong Buy"})["bullish"] is True
    assert sm.thesis_of({"verdict": "AVOID"})["bearish"] is True
    assert sm.thesis_of({})["bullish"] is False
