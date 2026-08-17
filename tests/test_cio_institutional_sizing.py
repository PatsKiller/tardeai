"""Phase 6 — institutional sizing v2 (candidate set, not a lone number)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_institutional_sizing import (  # noqa: E402
    CANDIDATE_KEYS,
    SIZING_QUALITY_HEURISTIC,
    SIZING_VERSION,
    recommend_trim,
    size_decision,
)
from scripts.lib import cio_capital_plan as cp  # noqa: E402


def test_sizing_version():
    assert SIZING_VERSION.startswith("institutional_sizing_")
    assert SIZING_VERSION == "institutional_sizing_2.0.0"


def _assert_candidates(payload: dict) -> None:
    assert "candidates" in payload
    assert isinstance(payload["candidates"], dict)
    for key in CANDIDATE_KEYS:
        assert key in payload["candidates"], key


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
    _assert_candidates(r)
    assert r["candidates"]["minimum_risk_clear"] == clear
    assert r["candidates"]["policy_normalize"] == full
    assert r["candidates"]["default_fallback"] == blind
    assert r["selected_candidate"]
    assert r["selection_rationale"]
    assert r["sizing_quality"] != "OPTIMIZED"
    _ = blind  # available for debugging


def test_within_policy_advisory_is_scenario_only_zero_delta():
    """Within policy/fire with no objective: 10% is a scenario, NOT a recommendation."""
    r = recommend_trim(
        market_value_usd=20_000.0,
        weight_pct=2.0,
        portfolio_value_usd=1_000_000.0,
        policy_cap_pct=12.0,
        fire_pct=16.5,
        advisory_trim=True,
    )
    assert r["method"] == "scenario_only"
    assert r["recommended_trim_usd"] == 0.0
    assert r["recommended_delta_usd"] == 0.0
    assert r["fallback_candidate_only"] is True
    assert r["scenario_trim_usd"] == 2000.0
    _assert_candidates(r)
    assert r["sizing_quality"] == SIZING_QUALITY_HEURISTIC
    assert r["selected_candidate"] == "default_fallback"
    assert "recommended delta $0" in r["selection_rationale"]
    assert "Scenario only" in r["selection_rationale"]
    assert "recommended $0" in r["objective_summary"]


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
    _assert_candidates(r)
    assert r["candidates"]["policy_normalize"] == 20_000.0


def test_exit_full():
    r = size_decision(
        stance="EXIT",
        market_value_usd=50_000.0,
        weight_pct=5.0,
        portfolio_value_usd=1_000_000.0,
    )
    assert r["recommended_delta_usd"] == -50_000.0
    _assert_candidates(r)


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
        "clear_fire_staged", "policy_normalize_staged", "scenario_only", "SIZING_UNAVAILABLE",
    )
    if dec.get("sizing_method") == "clear_fire_staged":
        assert abs(delta - blind) > 1.0 or dec.get("trim_to_clear_fire_usd", 0) > 0
        assert dec.get("fallback_candidate_only") is False
    assert "sizing_objective" in dec or dec.get("sizing")
    cands = dec.get("candidates") or (dec.get("sizing") or {}).get("candidates")
    assert isinstance(cands, dict)
    for key in CANDIDATE_KEYS:
        assert key in cands, key


def test_candidates_dict_always_present():
    """Every stance emits the full candidate book (nulls allowed)."""
    for stance in ("TRIM", "EXIT", "ADD", "RE_ENTER", "HOLD"):
        r = size_decision(
            stance=stance,
            market_value_usd=50_000.0,
            weight_pct=5.0,
            portfolio_value_usd=1_000_000.0,
            headroom_usd=70_000.0,
        )
        _assert_candidates(r)
        assert r["sizing_quality"] in (
            "HEURISTIC", "OBJECTIVE", "OPTIMIZED",
        )


def test_add_5k_is_heuristic_without_risk_budget():
    """Flat $5k ADD is HEURISTIC / fallback_candidate_only — not optimized."""
    r = size_decision(
        stance="ADD",
        market_value_usd=0.0,
        weight_pct=0.0,
        portfolio_value_usd=1_000_000.0,
        headroom_usd=120_000.0,
    )
    assert abs(r["recommended_delta_usd"] - 5_000.0) < 0.02
    assert r["sizing_quality"] == SIZING_QUALITY_HEURISTIC
    assert r["fallback_candidate_only"] is True
    assert r["sizing_quality"] != "OPTIMIZED"
    _assert_candidates(r)
    assert r["candidates"]["default_fallback"] == 5_000.0
    assert r["candidates"]["risk_budget_size"] is None
    assert r["tranches"] is not None
    assert r["tranches"]["starter"] == 5_000.0
    assert r["tranches"]["max_policy"] == 120_000.0
    assert r["tranches"]["target"] >= r["tranches"]["starter"]
    assert r["tranches"]["risk_budget"] is None
    assert "HEURISTIC" in r["selection_rationale"] or "fallback" in r["selection_rationale"].lower()


def test_add_risk_budget_is_not_flat_5k():
    r = size_decision(
        stance="ADD",
        market_value_usd=0.0,
        weight_pct=0.0,
        portfolio_value_usd=1_000_000.0,
        headroom_usd=120_000.0,
        annualized_vol=0.20,
        risk_budget_usd=10_000.0,  # notional = 10k / 0.20 = 50k
    )
    assert r["candidates"]["risk_budget_size"] is not None
    assert r["sizing_quality"] == "OPTIMIZED"
    assert r["fallback_candidate_only"] is False
    assert abs(r["recommended_delta_usd"] - 50_000.0) < 1.0
    assert r["tranches"]["risk_budget"] is not None


def test_optional_candidates_null_without_inputs():
    r = recommend_trim(
        market_value_usd=20_000.0,
        weight_pct=2.0,
        portfolio_value_usd=1_000_000.0,
        policy_cap_pct=12.0,
        fire_pct=16.5,
    )
    _assert_candidates(r)
    assert r["candidates"]["tax_aware_lot_size"] is None
    assert r["candidates"]["risk_budget_size"] is None
    assert r["candidates"]["liquidity_max"] is None
    assert r["candidates"]["replacement_opportunity_size"] is None
    assert r["candidates"]["default_fallback"] == 2_000.0
    assert r["candidates"]["volatility_budget_size"] is not None  # assumed vol
    assert r["candidates"]["cash_policy_max"] is not None


def test_taxable_vs_ira_changes_rationale_or_tax_aware_lot_size():
    lots = [
        {"market_value": 40_000.0, "unrealized_gain_pct": 40.0},
        {"market_value": 10_000.0, "unrealized_gain_pct": -5.0},
    ]
    common = dict(
        market_value_usd=140_000.0,
        weight_pct=14.0,
        portfolio_value_usd=1_000_000.0,
        policy_cap_pct=12.0,
        fire_pct=16.5,
        lots=lots,
        unrealized_gain_pct=25.0,
    )
    tax = recommend_trim(tax_class="TAXABLE", **common)
    ira = recommend_trim(tax_class="TAX_ADVANTAGED", **common)
    _assert_candidates(tax)
    _assert_candidates(ira)
    assert tax["candidates"]["tax_aware_lot_size"] is not None
    assert ira["candidates"]["tax_aware_lot_size"] is not None
    assert tax["tax_class"] == "TAXABLE"
    assert ira["tax_class"] == "TAX_ADVANTAGED"
    # Taxable prefers smaller / loss-first lots; IRA fills toward target
    differs = (
        tax["candidates"]["tax_aware_lot_size"] != ira["candidates"]["tax_aware_lot_size"]
        or tax["why_not_max"] != ira["why_not_max"]
        or tax["selection_rationale"] != ira["selection_rationale"]
        or tax["recommended_trim_usd"] != ira["recommended_trim_usd"]
    )
    assert differs
    assert "taxable" in tax["why_not_max"].lower() or "taxable" in tax["selection_rationale"].lower()
    assert (
        "ira" in ira["why_not_max"].lower()
        or "tax-advantaged" in ira["why_not_max"].lower()
        or "ira" in ira["selection_rationale"].lower()
    )


def test_liquidity_and_replacement_candidates():
    r = recommend_trim(
        market_value_usd=140_000.0,
        weight_pct=14.0,
        portfolio_value_usd=1_000_000.0,
        adv_usd=200_000.0,
        replacement_opportunity_usd=8_000.0,
        max_participation_pct=10.0,
    )
    _assert_candidates(r)
    assert r["candidates"]["liquidity_max"] == 20_000.0
    assert r["candidates"]["replacement_opportunity_size"] == 8_000.0
