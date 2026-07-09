#!/usr/bin/env python3
"""MULTI-STRATEGY OPTIONS Stage 1 — strategy matcher (operator spec Part C).

Covers: run_matchers API shape, thesis gating both sides (bullish for atm_call,
bearish for atm_put — watchlist verdicts, held-with-positive-thesis, explicit
bearish thesis, hedge-of-held), deep_itm_call delegation to the existing
generator (pass / watch / fail), watch status on disclosed-flag-only issues,
the not_applicable set with honest reasons (covered_call / cash_secured_put /
protective_put / credit_spread), cross_strategy_summary shape, in-strategy
ranking, and the pure-library guarantee (no queue writes, no broker imports).

EARNINGS-SPREADS Stage 2 (spec Part E): the earnings_put_debit_spread lane —
not_applicable outside the event window ("no earnings in window"), fail on a
missing bearish/hedge thesis or event_confidence below the registry gate,
pass/watch via the earnings vertical generator (watch on disclosed-flag-only
proposals: iv_rich / historical_move_below_breakeven), chain-unavailable
degrade, injectable event_json/earnings_fn, and the credit id staying honest
not_applicable "blocked initially (BLOCKED_INITIAL)".

    .venv/bin/python -m pytest tests/test_options_strategy_matcher.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from unittest.mock import patch

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
    entry_plan = kw.pop("entry_plan", {})
    with patch.object(sm, "_fetch_entry_plan", return_value=entry_plan):
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
    # every registry strategy is reported (9 rows after EARNINGS-SPREADS
    # Stage 1 — the earnings pair surfaces as honest not_applicable until
    # Stage 2 wires its matcher)
    assert set(results) == {"deep_itm_call", "covered_call", "cash_secured_put",
                            "protective_put", "credit_spread",
                            "atm_call", "atm_put",
                            "earnings_put_debit_spread",
                            "earnings_put_credit_spread"}
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
    for sid in ("protective_put", "credit_spread"):
        assert res[sid]["status"] == "not_applicable", sid
        assert res[sid]["proposals"] == [], sid
    assert res["covered_call"]["status"] == "not_applicable"
    assert "requires 100 held shares" in res["covered_call"]["reason"]
    assert res["cash_secured_put"]["status"] == "fail"
    assert "no entry-plan strike" in res["cash_secured_put"]["reason"]
    assert "requires existing long exposure" in res["protective_put"]["reason"]
    assert "RESEARCH_ONLY" in res["credit_spread"]["reason"]


def test_not_applicable_reasons_acknowledge_held_shares():
    res = _run({"verdict": "buy", "held_shares": 200.0})["strategy_results"]
    assert res["covered_call"]["status"] in ("watch", "pass")
    assert "writable" in res["covered_call"]["reason"].lower()
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
    assert cs["considered"] == 9        # 9 registry rows after EARNINGS-SPREADS Stage 1
    assert sorted(cs["pass"]) == ["atm_call", "deep_itm_call"]
    assert cs["fail"] == ["atm_put", "cash_secured_put"]
    assert sorted(cs["not_applicable"]) == ["covered_call", "credit_spread",
                                            "earnings_put_credit_spread",
                                            "earnings_put_debit_spread",
                                            "protective_put"]
    assert cs["counts"] == {"pass": 2, "watch": 0, "fail": 2, "not_applicable": 5}
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


# ── (9) EARNINGS-SPREADS Stage 2 — earnings_put_debit_spread lane (Part E) ───

EARN_EXP = "2026-08-07"


def _earn_contract(side, strike, mid, *, delta=None, oi=600, volume=60):
    # tight quotes (±0.02) keep the two-leg package slippage under the 8% gate
    return {"side": side, "strike": float(strike), "bid": round(mid - 0.02, 4),
            "ask": round(mid + 0.02, 4), "mid": mid,
            "spread_pct": round(0.04 / mid * 100.0, 2), "volume": volume,
            "oi": oi, "delta": delta, "iv": 40.0, "dte": 33,
            "liquidity_score": 70}


def _earn_snapshot():
    """Put ladder rich enough for the vertical generator at the event expiry."""
    return {"available": True, "symbol": "NVDA", "underlying_price": SPOT,
            "expirations": [
                {"exp": EARN_EXP, "dte": 33, "liquidity_score": 70,
                 "contracts": [
                     _earn_contract("call", 100.0, 1.0, delta=0.50),
                     _earn_contract("put", 100.0, 4.0, delta=-0.52),
                     _earn_contract("put", 97.5, 3.0, delta=-0.40),
                     _earn_contract("put", 95.0, 2.0, delta=-0.30),
                     _earn_contract("put", 90.0, 1.0, delta=-0.15),
                 ]},
            ],
            "liquidity_score": 70}


def _earn_event(*, in_window=True, days=5, confidence=0.80, flags=()):
    """Hand-built event_json (the shape earnings_event_model emits) —
    fully deterministic for the matcher-lane tests."""
    return {"symbol": "NVDA", "days_to_earnings": days,
            "earnings_date": {"date": "2026-08-05", "source": "test"},
            "event_window": {"days_before": 10, "days_after": 2,
                             "in_window": in_window},
            "nearest_expiration_after_earnings": {"available": True,
                                                  "exp": EARN_EXP, "dte": 33},
            "implied_move_pct": {"available": True, "pct": 5.0,
                                 "method": "atm_straddle_mid"},
            "historical_earnings_moves": {"available": False,
                                          "reason": "test fixture"},
            "iv_context": {"available": False, "reason": "test fixture"},
            "post_earnings_iv_crush_estimate": {"available": False,
                                                "reason": "test fixture"},
            "event_thesis": "bearish", "event_thesis_source": "watchlist_sell",
            "event_confidence": confidence, "risk_flags": list(flags),
            "educational_only": True}


def _run_earn(context, **kw):
    kw.setdefault("snapshot", _earn_snapshot())
    kw.setdefault("event_json", _earn_event())
    return sm.run_matchers("NVDA", context,
                           ["earnings_put_debit_spread"], **kw)


def test_earnings_not_applicable_outside_window():
    res = _run_earn(BEARISH, event_json=_earn_event(in_window=False, days=30))
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert r["status"] == "not_applicable"
    assert "no earnings in window" in r["reason"]
    assert r["proposals"] == []


def test_earnings_not_applicable_without_event_date_via_injected_date():
    # no injected event_json: the lane builds one from the injected snapshot
    # and the far-future caller earnings_date → honest not_applicable
    res = sm.run_matchers("NVDA", BEARISH, ["earnings_put_debit_spread"],
                          snapshot=_earn_snapshot(), earnings_date=NO_EARNINGS)
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert r["status"] == "not_applicable"
    assert "no earnings in window" in r["reason"]


def test_earnings_fail_on_missing_bearish_thesis():
    res = _run_earn(BULLISH)
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert r["status"] == "fail"
    assert "bearish/hedge thesis missing" in r["reason"]
    assert r["proposals"] == []


def test_earnings_fail_below_confidence_gate():
    res = _run_earn(BEARISH, event_json=_earn_event(confidence=0.40))
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert r["status"] == "fail"
    assert "event_confidence 0.40 below gate 0.65" in r["reason"]


def test_earnings_pass_generates_debit_spreads():
    res = _run_earn(BEARISH)
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert r["status"] == "pass", r["reason"]
    assert r["proposals"]
    p = r["proposals"][0]
    assert p["strategy"] == "earnings_put_debit_spread"
    assert p["strategy_family"] == "earnings_vertical_debit"
    assert p["long_strike"] == 100.0 and p["expiration"] == EARN_EXP
    assert p["enterprise"]["live_eligible"] is False
    assert p["paper_only"] is True
    # implied move 5% → boundary 95 → expected-move short strike selected
    shorts = {q["short_strike"] for q in r["proposals"]}
    assert 95.0 in shorts
    assert r["event"]["implied_move_pct"] == 5.0
    assert r["event"]["in_window"] is True


def test_earnings_hedge_of_held_passes():
    ctx = {"verdict": None, "held_shares": 100.0, "hedge_of_held": True}
    res = _run_earn(ctx)
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert r["status"] == "pass", r["reason"]
    intel = r["proposals"][0]["meta"]["underlying_intel"]
    assert intel["conviction_source"] == "hedge_of_held"


def test_earnings_watch_on_disclosed_iv_rich_flag():
    res = _run_earn(BEARISH, event_json=_earn_event(flags=("iv_rich",)))
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert r["status"] == "watch"
    assert "disclosed flags" in r["reason"] and "iv_rich" in r["reason"]
    assert all("iv_rich" in p["meta"]["gate_flags"] for p in r["proposals"])


def test_earnings_fail_when_chain_unavailable():
    res = _run_earn(BEARISH,
                    snapshot={"available": False, "reason": "weekend — no chain"})
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert r["status"] == "fail"
    assert "chain unavailable" in r["reason"] and "weekend" in r["reason"]


def test_earnings_credit_stays_blocked_not_applicable():
    res = sm.run_matchers("NVDA", BEARISH, ["earnings_put_credit_spread"],
                          snapshot=_earn_snapshot())
    r = res["strategy_results"]["earnings_put_credit_spread"]
    assert r["status"] == "not_applicable"
    assert "blocked initially" in r["reason"].lower() \
        or "BLOCKED_INITIAL" in r["reason"]
    assert "BLOCKED_INITIAL" in r["reason"]
    assert r["proposals"] == []


def test_earnings_injectable_generator_fn():
    seen = {}

    def fake_gen(sym, ev, cfg, thesis_ctx, **kw):
        seen["sym"] = sym
        seen["conviction_source"] = thesis_ctx.get("conviction_source")
        return {"available": True, "proposals": [], "reject_notes": ["all rejected"]}

    res = _run_earn(BEARISH, earnings_fn=fake_gen)
    r = res["strategy_results"]["earnings_put_debit_spread"]
    assert seen["sym"] == "NVDA"
    assert seen["conviction_source"] == "watchlist_sell"
    assert r["status"] == "fail"
    assert "no candidates passed gates" in r["reason"]
    assert "all rejected" in r["reason"]


# ── (10) context resolution stays honest offline ─────────────────────────────

def test_verdict_normalization():
    assert sm._normalize_verdict("Strong Buy") == "strong_buy"
    assert sm._normalize_verdict("STRONG-SELL") == "strong_sell"
    assert sm._normalize_verdict(None) is None
    assert sm.thesis_of({"verdict": "Strong Buy"})["bullish"] is True
    assert sm.thesis_of({"verdict": "AVOID"})["bearish"] is True
    assert sm.thesis_of({})["bullish"] is False
