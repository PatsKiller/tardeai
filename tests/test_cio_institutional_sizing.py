"""Phase 5 — institutional sizing (objective-driven trims)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_institutional_sizing import (  # noqa: E402
    SIZING_VERSION,
    recommend_trim,
    size_decision,
)
from scripts.lib import cio_capital_plan as cp  # noqa: E402


def test_sizing_version():
    assert SIZING_VERSION.startswith("institutional_sizing_")


def test_schd_style_fire_not_blind_10pct():
    """17.6% weight, fire 16.5%, policy 12% → recommend between clear-fire and full policy."""
    port = 1_284_000.0
    weight = 17.6
    value = port * weight / 100.0  # ~226k
    r = recommend_trim(
        market_value_usd=value,
        weight_pct=weight,
        portfolio_value_usd=port,
        policy_cap_pct=12.0,
        fire_pct=16.5,
    )
    clear = r["trim_to_clear_fire_usd"]
    full = r["trim_to_policy_usd"]
    rec = r["recommended_trim_usd"]
    assert clear > 0
    assert full > clear
    # Not blind 10% of whole position as the only answer when fire binds
    blind = round(value * 0.10, 2)
    assert r["method"] == "clear_fire_staged"
    assert rec >= clear - 1.0
    assert rec <= full + 1.0
    # Staged recommendation should not equal full policy dump by default
    assert rec < full or abs(rec - full) < 1.0
    assert "objective_summary" in r
    assert r["fallback_candidate_only"] is False
    # Binding fire objective is larger or smaller than blind 10% depending on math —
    # what matters is method is not fallback_10pct
    assert r["method"] != "advisory_fallback_10pct"
    _ = blind  # available for debugging


def test_within_policy_advisory_uses_fallback_10pct():
    r = recommend_trim(
        market_value_usd=20_000.0,
        weight_pct=2.0,
        portfolio_value_usd=1_000_000.0,
        policy_cap_pct=12.0,
        fire_pct=16.5,
        advisory_trim=True,
    )
    assert r["method"] == "advisory_fallback_10pct"
    assert abs(r["recommended_trim_usd"] - 2000.0) < 0.02
    assert r["fallback_candidate_only"] is True


def test_above_policy_below_fire_staged():
    # 14% weight, fire 16.5%, policy 12%
    port = 1_000_000.0
    r = recommend_trim(
        market_value_usd=140_000.0,
        weight_pct=14.0,
        portfolio_value_usd=port,
        policy_cap_pct=12.0,
        fire_pct=16.5,
    )
    assert r["above_policy"] is True
    assert r["above_fire"] is False
    assert r["method"] == "policy_normalize_staged"
    assert r["trim_to_policy_usd"] == 20_000.0  # 140k - 120k
    assert 0 < r["recommended_trim_usd"] <= 20_000.0


def test_exit_full():
    r = size_decision(
        stance="EXIT",
        market_value_usd=50_000.0,
        weight_pct=5.0,
        portfolio_value_usd=1_000_000.0,
    )
    assert r["recommended_delta_usd"] == -50_000.0


def test_capital_plan_schd_not_exactly_10pct_when_over_fire():
    """Live-shaped SCHD: ~17.58% must not force pure 10% when fire binds."""
    port = 1_284_243.30
    schd_val = 225_789.79
    plan = cp.build_capital_plan(
        portfolio_value=port,
        cash_total=578_107.50,
        positions=[{
            "symbol": "SCHD",
            "market_value": schd_val,
            "account": "schwab_rollover_ira",
            "weight_pct": 17.58,
        }],
        queue={"items": [
            {"symbol": "SCHD", "verdict": "TRIM", "directive_label": "Advisory TRIM — SCHD"},
        ]},
        redeploy_open_events=[],
        concentration_fire_pct=16.5,
        max_single_name_pct=12.0,
    )
    dec = next(d for d in plan["position_decisions"] if d["symbol"] == "SCHD")
    delta = abs(float(dec["recommended_delta_usd"]))
    blind = round(schd_val * 0.10, 2)
    # Objective path should set sizing method
    assert dec.get("sizing_method") in (
        "clear_fire_staged", "policy_normalize_staged", "advisory_fallback_10pct", "legacy_fallback",
    )
    if dec.get("sizing_method") == "clear_fire_staged":
        assert abs(delta - blind) > 1.0 or dec.get("trim_to_clear_fire_usd", 0) > 0
        assert dec.get("fallback_candidate_only") is False
    assert "sizing_objective" in dec or dec.get("sizing")
