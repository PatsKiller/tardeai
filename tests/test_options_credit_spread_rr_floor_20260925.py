"""Credit-spread R:R floor — refuse asymmetric payoff (2026-09-25).

AMZN live-eligible Tier A with max profit $66 / max loss $1,184 (R:R 0.06)
proved Ideas ranked POP, not payoff asymmetry. Floor default 0.25.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ent():
    return _load("options_desk_enterprise_rr", "scripts/options_desk_enterprise.py")


def test_amzn_class_rr_refused(ent):
    """$66 credit / $1,184 risk must never clear the floor."""
    p = {
        "strategy": "credit_spread",
        "symbol": "AMZN",
        "max_profit": 66,
        "max_loss": 1184,
        "risk_reward": 0.06,
        "premium_total": 66,
        "short_strike": 232.5,
        "long_strike": 220.0,
    }
    reason = ent.credit_spread_rr_block(p, cfg={"min_credit_spread_rr": 0.25})
    assert reason is not None
    assert "0.060" in reason or "0.06" in reason
    assert "asymmetric" in reason.lower() or "refused" in reason.lower()


def test_fair_credit_spread_passes(ent):
    p = {
        "strategy": "credit_spread",
        "max_profit": 250,
        "max_loss": 750,
        "risk_reward": 0.333,
    }
    assert ent.credit_spread_rr_block(p, cfg={"min_credit_spread_rr": 0.25}) is None


def test_csp_not_gated_by_credit_spread_rr(ent):
    """Cash-secured put assignment economics are out of scope for this floor."""
    p = {
        "strategy": "cash_secured_put",
        "max_profit": 200,
        "max_loss": 15000,
        "risk_reward": 0.013,
    }
    assert ent.credit_spread_rr_block(p, cfg={"min_credit_spread_rr": 0.25}) is None


def test_enterprise_enrich_blocks_live_eligible(ent):
    p = {
        "strategy": "credit_spread",
        "symbol": "AMZN",
        "edge_score": 76,
        "dte": 21,
        "max_profit": 66,
        "max_loss": 1184,
        "risk_reward": 0.06,
        "data_source": "schwab_chain",
        "underlying_price": 249.0,
    }
    # Fake liquid contract so liquidity alone would pass.
    contract = {"bid": 0.60, "ask": 0.70, "mid": 0.65, "oi": 500, "volume": 40}
    out = ent.enterprise_enrich_proposal(p, contract=contract, cfg={
        "min_credit_spread_rr": 0.25,
        "require_chain_for_live": True,
        "min_open_interest": 50,
        "min_volume": 5,
        "max_bid_ask_spread_pct": 12.0,
        "desk_tier_edge_a": 72,
        "desk_tier_edge_b": 62,
        "earnings_blackout_days": 14,
    })
    ent_meta = out.get("enterprise") or {}
    assert ent_meta.get("live_eligible") is False
    blocks = ent_meta.get("blocks") or []
    assert any("R:R" in str(b) or "asymmetric" in str(b).lower() for b in blocks)


def test_hard_risk_blocks_include_rr_code(ent):
    p = {
        "strategy": "credit_spread",
        "symbol": "AMZN",
        "max_profit": 66,
        "max_loss": 1184,
        "risk_reward": 0.06,
        "contracts": 1,
        "enterprise": {"liquidity": {"pass": True}},
    }
    blocks = ent.evaluate_hard_risk_blocks(p, mode="live", cfg={"min_credit_spread_rr": 0.25})
    codes = [b.get("code") for b in blocks]
    assert "credit_spread_rr_below_floor" in codes


def test_floor_disableable(ent):
    p = {
        "strategy": "credit_spread",
        "max_profit": 66,
        "max_loss": 1184,
        "risk_reward": 0.06,
    }
    assert ent.credit_spread_rr_block(p, cfg={"min_credit_spread_rr": 0}) is None
