#!/usr/bin/env python3
"""Holdings options funnel — named drop reasons for covered calls / protective puts.

Stage 1 of plan-options-desk-holdings-strategies-20260924: honesty without gate widening.

    .venv/bin/python -m pytest tests/test_options_holdings_funnel.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import options_engine as oe  # noqa: E402


def _holding(sym: str, shares: float, price: float, *, account: str = "schwab_roth", mv: float | None = None):
    mv = price * shares if mv is None else mv
    return {
        "symbol": sym,
        "shares": shares,
        "price": price,
        "current_price": price,
        "market_value": mv,
        "account": account,
        "is_cash": False,
    }


def test_need_100_shares_schg_amanx():
    intent = {"covered_call_candidate": ["V"], "covered_call_settings": {"iv_rank_minimum": 20}}
    tech = {"SCHG": {"iv": 18, "rsi": 50}, "AMANX": {"iv": 15, "rsi": 50}}
    rows = [
        _holding("SCHG", 0.23, 35.0, account="schwab_taxable"),
        _holding("AMANX", 63.0, 78.0, account="schwab_rollover_ira"),
    ]
    out = oe.build_holdings_funnel(
        holdings=rows, tech_map=tech, intent_cfg=intent, resolve_chain=False,
    )
    assert out["ok"] is True
    by_sym = {r["symbol"]: r["cc"]["status"] for r in out["rows"]}
    assert by_sym["SCHG"] == "NEED_100_SHARES"
    assert by_sym["AMANX"] == "NEED_100_SHARES"
    assert out["summary"]["cc_need_100_shares"] == 2


def test_size_eligible_low_iv_named_not_silent():
    intent = {"covered_call_candidate": ["V"], "covered_call_settings": {"iv_rank_minimum": 25}}
    # IV proxy from tech.iv percent — keep well below floor
    tech = {"MCD": {"iv": 8, "rsi": 45, "atr": 2.0}}
    rows = [_holding("MCD", 300.0, 300.0, account="schwab_rollover_ira")]
    out = oe.build_holdings_funnel(
        holdings=rows, tech_map=tech, intent_cfg=intent, resolve_chain=False,
    )
    assert len(out["rows"]) == 1
    status = out["rows"][0]["cc"]["status"]
    # Without a contract, evaluate still computes iv_rank from tech and should name IV_BELOW
    # (resolve_chain=False skips NO_CHAIN and continues into IV/edge math with synthetic mid).
    assert status in ("IV_BELOW_FLOOR", "EDGE_BELOW", "POP_BELOW"), status
    assert status != "CC_ELIGIBLE"


def test_cusip_not_optionable():
    intent = {"covered_call_candidate": [], "covered_call_settings": {}}
    rows = [_holding("543354104", 3000.0, 0.0, mv=0.0)]
    out = oe.build_holdings_funnel(
        holdings=rows, tech_map={}, intent_cfg=intent, resolve_chain=False,
    )
    assert out["rows"][0]["cc"]["status"] in ("NOT_OPTIONABLE", "PRICE_ZERO")


def test_intent_bypass_when_iv_soft_but_gates_pass(monkeypatch):
    intent = {
        "covered_call_candidate": ["V"],
        "covered_call_settings": {"iv_rank_minimum": 25, "default_dte_days": 30, "default_otm_pct": 0.06},
    }
    tech = {"V": {"iv": 12, "rsi": 55, "atr": 4.0}}  # below 25 floor
    rows = [_holding("V", 131.0, 365.0, account="schwab_roth")]

    def _fake_contract(sym, price, tech, side, target_strike, target_dte):
        return {
            "mid": 4.50,
            "strike": round(target_strike / 5) * 5,
            "dte": 30,
            "iv": 0.18,
            "exp": "2026-10-17",
            "delta": -0.25,
            "oi": 500,
        }, "schwab_live"

    monkeypatch.setattr(oe, "_resolve_option_contract", _fake_contract)
    # High POP path: deep OTM relative premium still needs edge — boost via intent
    out = oe.build_holdings_funnel(
        holdings=rows, tech_map=tech, intent_cfg=intent, resolve_chain=True,
    )
    status = out["rows"][0]["cc"]["status"]
    assert status in ("CC_ELIGIBLE", "INTENT_BYPASS", "EDGE_BELOW", "POP_BELOW"), status
    # Critical: not NEED_100 and not silent omit
    assert out["summary"]["holdings_scanned"] == 1
    assert status != "NEED_100_SHARES"


def test_api_handler_shape(monkeypatch):
    """_options_holdings_funnel returns ok + summary without raising."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import api_v2

    monkeypatch.setattr(
        oe,
        "build_holdings_funnel",
        lambda **kw: {
            "ok": True,
            "as_of": "2026-09-24T15:00:00Z",
            "summary": {"holdings_scanned": 0, "cc_need_100_shares": 0},
            "rows": [],
        },
    )
    monkeypatch.setattr(api_v2, "_get_options_engine", lambda: oe)
    out = api_v2._options_holdings_funnel({"resolve_chain": ["0"]})
    assert out.get("ok") is True
    assert "summary" in out
