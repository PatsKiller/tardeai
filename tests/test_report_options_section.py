#!/usr/bin/env python3
"""Prospectus §15 options strategy fit + CIO context resolution."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import strategy_matcher as sm  # noqa: E402
from report_narrative import action_recommendation_line  # noqa: E402
from analyst_report_builder import _options_income_section  # noqa: E402


def test_cio_verdict_beats_research_card():
    with patch.object(sm, "_fetch_watchlist_verdicts", return_value={
        "cio_verdict": "avoid", "card_verdict": "hold",
        "grok_verdict": None, "chatgpt_verdict": None,
    }):
        ctx = sm.resolve_context("FATN")
    assert ctx["verdict"] == "avoid"
    assert ctx["cio_verdict"] == "avoid"
    thesis = sm.thesis_of(ctx)
    assert thesis["bearish"] is True
    assert thesis["bearish_source"] == "watchlist_avoid"


def test_csp_at_plan_limit_with_avoid_is_watch():
    snap = {
        "available": True, "symbol": "FATN", "underlying_price": 5.30,
        "expirations": [{
            "exp": "2026-08-07", "dte": 33,
            "contracts": [{
                "side": "put", "strike": 4.95, "bid": 0.18, "ask": 0.22, "mid": 0.20,
                "delta": -0.35, "iv": 80, "volume": 12, "oi": 250, "spread_pct": 4.0,
                "dte": 33, "liquidity_score": 65, "exp": "2026-08-07",
            }],
        }],
    }
    ctx = {"verdict": "avoid", "cio_verdict": "avoid", "plan_zone_low": 4.95, "plan_entry": 5.05}
    res = sm.run_matchers("FATN", ctx, strategies=["cash_secured_put"],
                          snapshot=snap, iv_context={"available": False})
    csp = res["strategy_results"]["cash_secured_put"]
    assert csp["status"] in ("pass", "watch")
    assert csp["proposals"]
    assert csp["proposals"][0]["strike"] == 4.95


def test_action_avoid_zero_shares():
    line = action_recommendation_line(
        "AVOID", price=5.30, proposal=None, pro=None, thesis="Still valid",
        levels={"stop": 4.49}, held_shares=0,
    )
    assert "do not initiate" in line.lower()
    assert "off-book" in line.lower()


def test_options_section_wires_matcher():
    fake_match = {
        "context": {"cio_verdict": "avoid", "verdict": "avoid", "held_shares": 0,
                    "plan_entry": 5.05, "plan_zone_low": 4.95},
        "strategy_results": {
            "cash_secured_put": {"status": "watch", "reason": "entry plan vs CIO", "proposals": [{
                "strike": 4.95, "dte": 33, "edge_score": 62, "strategy": "cash_secured_put",
            }]},
            "atm_put": {"status": "pass", "reason": "bearish thesis", "proposals": []},
            "covered_call": {"status": "not_applicable", "reason": "requires 100 shares", "proposals": []},
        },
        "cross_strategy_summary": {"considered": 9, "counts": {"pass": 1, "watch": 1, "fail": 0, "not_applicable": 1},
                                   "best_proposal": {"strategy": "atm_put", "strike": 5.0, "edge_score": 70}},
    }
    with patch("lib.options_pipeline.strategy_matcher.run_matchers", return_value=fake_match):
        sec = _options_income_section(
            "FATN", {"price": 5.30, "instrument_type": "stock"}, None, {"shares": 0},
            synthesis={"recommendation": "AVOID"}, proposal=None,
            levels={"entry": 5.05, "stop": 4.49, "valid_low": 4.95},
        )
    assert sec["title"] == "Options Strategy Fit"
    assert "cio avoid" in sec["content"].lower()
    assert any("Cash-Secured Put" in b for b in sec["bullets"])
    assert sec["metrics"]["plan_entry"] == 5.05