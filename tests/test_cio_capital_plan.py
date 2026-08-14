"""cio_capital_plan.py — dry tests for Alex's capital plan + decision engine.

Phase 6: deterministic, advisory-only Capital Plan projection and Position
Decision table. Pure logic is tested with no live DB/broker/LLM.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_capital_plan as cp  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Policy helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_cash_policy_band():
    band = cp.cash_policy_band(100_000.0, min_pct=20.0, max_pct=25.0)
    assert band["min_usd"] == 20_000.0
    assert band["max_usd"] == 25_000.0


def test_cash_policy_band_defaults():
    band = cp.cash_policy_band(100_000.0)
    assert band["min_pct"] == cp.CASH_BAND_DEFAULT_MIN_PCT
    assert band["max_pct"] == cp.CASH_BAND_DEFAULT_MAX_PCT


def test_cash_posture_above_band():
    p = cp.cash_posture(30_000.0, 100_000.0, min_pct=20.0)
    assert p["status"] == "ABOVE_BAND"
    assert p["reserve_usd"] == 20_000.0
    assert p["investable_usd"] == 10_000.0
    assert p["cash_pct"] == 30.0


def test_cash_posture_in_band():
    p = cp.cash_posture(15_000.0, 100_000.0, min_pct=20.0)
    assert p["status"] == "IN_BAND"
    assert p["investable_usd"] == 0.0


def test_cash_posture_below_band():
    p = cp.cash_posture(5_000.0, 100_000.0, min_pct=20.0)
    assert p["status"] == "BELOW_BAND"
    assert p["investable_usd"] == 0.0


def test_cash_posture_no_portfolio():
    p = cp.cash_posture(0.0, 0.0, min_pct=20.0)
    assert p["status"] == "NO_PORTFOLIO"


# ─────────────────────────────────────────────────────────────────────────────
# Account tax classification
# ─────────────────────────────────────────────────────────────────────────────

def test_classify_account_tax_config_taxable():
    assert cp.classify_account_tax(
        "schwab_taxable", {"schwab_taxable": {"taxable": True}}) == "TAXABLE"


def test_classify_account_tax_config_advantaged():
    assert cp.classify_account_tax(
        "schwab_rollover_ira", {"schwab_rollover_ira": {"taxable": False}}) == "TAX_ADVANTAGED"


def test_classify_account_tax_config_type():
    assert cp.classify_account_tax(
        "schwab_roth", {"schwab_roth": {"type": "roth_ira"}}) == "TAX_ADVANTAGED"


def test_classify_account_tax_name_inference():
    # even without config, ira/roth/401k hints are tax-advantaged
    assert cp.classify_account_tax("fidelity_rollover_ira") == "TAX_ADVANTAGED"
    assert cp.classify_account_tax("schwab_roth") == "TAX_ADVANTAGED"
    assert cp.classify_account_tax("some_401k") == "TAX_ADVANTAGED"


def test_classify_account_tax_unknown_is_taxable():
    # unknown account is treated as taxable (never silently waive tax constraints)
    assert cp.classify_account_tax("alpaca_taxable_live") == "TAXABLE"


# ─────────────────────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_position_skips_cash_and_empty():
    assert cp.normalize_position({"symbol": "CASH", "is_cash": True, "market_value": 10}, 100.0) is None
    assert cp.normalize_position({"symbol": "", "market_value": 10}, 100.0) is None
    assert cp.normalize_position({"symbol": "ABC", "market_value": 0}, 100.0) is None
    assert cp.normalize_position("not-a-dict", 100.0) is None


def test_normalize_position_shape():
    p = cp.normalize_position(
        {"symbol": "nvda", "market_value": 50_000.0, "account": "schwab_rollover_ira",
         "quantity": 100, "updated_at": "2026-08-10T00:00:00+00:00"},
        500_000.0,
    )
    assert p["symbol"] == "NVDA"
    assert p["market_value_usd"] == 50_000.0
    assert p["weight_pct"] == 10.0
    assert p["tax_class"] == "TAX_ADVANTAGED"  # name inference


# ─────────────────────────────────────────────────────────────────────────────
# Stance
# ─────────────────────────────────────────────────────────────────────────────

def test_stance_precedence():
    queue = {"items": [
        {"symbol": "A", "verdict": "TRIM"},
        {"symbol": "B", "verdict": "EXIT"},
        {"symbol": "C", "state": "READY TO REVIEW"},
        {"symbol": "D", "verdict": "ADD"},
    ]}
    assert cp.stance_for("B", queue) == "EXIT"
    assert cp.stance_for("A", queue) == "TRIM"
    assert cp.stance_for("D", queue) == "ADD"
    assert cp.stance_for("C", queue) == "RE_ENTER"  # reentry state
    assert cp.stance_for("ZZZ", queue) == "HOLD"


def test_stance_empty_queue_hold():
    assert cp.stance_for("NVDA", None) == "HOLD"
    assert cp.stance_for("NVDA", {"items": []}) == "HOLD"


# ─────────────────────────────────────────────────────────────────────────────
# Sources of funds
# ─────────────────────────────────────────────────────────────────────────────

def _positions():
    return [
        cp.normalize_position({"symbol": "NVDA", "market_value": 60_000.0, "account": "schwab_taxable"}, 500_000.0),
        cp.normalize_position({"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"}, 500_000.0),
    ]


def test_sources_trims_and_exits():
    queue = {"items": [
        {"symbol": "V", "verdict": "TRIM", "source": "cio"},
        {"symbol": "NVDA", "verdict": "EXIT", "source": "advisory"},
    ]}
    src = cp.build_capital_sources(_positions(), queue=queue)
    # V trim 10% of 40k = 4k; NVDA exit = full 60k
    assert src["trims_usd"] == 4_000.0
    assert src["exits_usd"] == 60_000.0
    assert src["total_raise_usd"] == 64_000.0
    assert len(src["trims"]) == 1 and src["trims"][0]["symbol"] == "V"
    assert len(src["exits"]) == 1 and src["exits"][0]["symbol"] == "NVDA"


def test_sources_maturities_positive_only():
    events = [
        {"event_id": 1, "symbol": "AAPL", "remaining_usd": 5_000.0},
        {"event_id": 2, "symbol": "MSFT", "remaining_usd": 0.0},
        {"event_id": 3, "symbol": "GOOG", "remaining_usd": None},
    ]
    src = cp.build_capital_sources(_positions(), redeploy_open_events=events)
    assert src["maturities_usd"] == 5_000.0
    assert len(src["maturities_distributions"]) == 1
    # Phase 2: earmarked redeploy is NOT part of total_raise
    assert src["earmarked_redeploy_usd"] == 5_000.0
    assert src["total_raise_usd"] == 0.0
    assert src["total_prospective_raise_usd"] == 0.0
    assert src["double_count_guard"] == "earmarked_redeploy_excluded_from_raise"
    assert src["maturities_distributions"][0]["already_in_cash"] is True


def test_sources_empty():
    src = cp.build_capital_sources(_positions())
    assert src["total_raise_usd"] == 0.0
    assert src["trims"] == [] and src["exits"] == [] and src["maturities_distributions"] == []


def test_sources_maturities_excluded_from_raise_even_with_trims():
    """Phase 2 double-count fix: total_raise = trims+exits only."""
    queue = {"items": [{"symbol": "V", "verdict": "TRIM", "source": "cio"}]}
    events = [{"event_id": 9, "symbol": "AAPL", "remaining_usd": 50_000.0}]
    src = cp.build_capital_sources(
        _positions(), queue=queue, redeploy_open_events=events, cash_total=100_000.0,
    )
    assert src["trims_usd"] == 4_000.0
    assert src["maturities_usd"] == 50_000.0
    assert src["earmarked_redeploy_usd"] == 50_000.0
    assert src["total_prospective_raise_usd"] == 4_000.0
    assert src["total_raise_usd"] == 4_000.0  # NOT 54_000
    assert src["double_count_guard"] == "earmarked_redeploy_excluded_from_raise"


def test_sources_earmark_capped_to_cash():
    events = [{"event_id": 1, "symbol": "X", "remaining_usd": 200_000.0}]
    src = cp.build_capital_sources(
        _positions(), redeploy_open_events=events, cash_total=50_000.0,
    )
    assert src["maturities_raw_usd"] == 200_000.0
    assert src["maturities_usd"] == 50_000.0
    assert src["maturities_capped_to_cash"] is True
    assert src["total_raise_usd"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Uses of funds
# ─────────────────────────────────────────────────────────────────────────────

def test_uses_adds_bounded_by_headroom():
    queue = {"items": [{"symbol": "NVDA", "verdict": "ADD", "source": "advisory"}]}
    posture = cp.cash_posture(100_000.0, 500_000.0, min_pct=20.0)
    # NVDA current 60k, cap 12% of 500k = 60k → headroom 0 → add = 0
    uses = cp.build_capital_uses(queue, _positions(), [], posture, 500_000.0)
    assert uses["adds_usd"] == 0.0
    # A fresh symbol gets headroom = full cap = 60k → add = 5k (default size)
    queue2 = {"items": [{"symbol": "TSLA", "verdict": "ADD", "source": "advisory"}]}
    uses2 = cp.build_capital_uses(queue2, _positions(), [], posture, 500_000.0)
    assert uses2["adds_usd"] == cp.NEW_POSITION_DEFAULT_USD


def test_uses_reentry_and_new_positions():
    queue = {"items": [
        {"symbol": "AA", "state": "READY TO REVIEW", "source": "reentry"},
        {"symbol": "BB", "source": "rotation"},  # no verdict/state → new position
        {"symbol": "CC", "verdict": "RE_ENTER", "source": "advisory"},
    ]}
    posture = cp.cash_posture(100_000.0, 500_000.0, min_pct=20.0)
    uses = cp.build_capital_uses(queue, [], [], posture, 500_000.0)
    assert uses["reentry_usd"] == cp.NEW_POSITION_DEFAULT_USD * 2  # AA + CC
    assert uses["new_positions_usd"] == cp.NEW_POSITION_DEFAULT_USD  # BB


def test_uses_sector_rotation_underweight_only():
    posture = cp.cash_posture(100_000.0, 500_000.0, min_pct=20.0)
    opps = [
        {"sector": "Energy", "state": "IMPROVING", "opportunity": True,
         "current_exposure_pct": 4.0, "target_posture_pct": 5.0,
         "recommendation": "STAGED_DEPLOYMENT"},
        {"sector": "Technology", "state": "LEADING", "opportunity": True,
         "current_exposure_pct": 25.0, "target_posture_pct": 18.0,
         "recommendation": "NO_DEPLOYMENT"},
        {"sector": "Materials", "state": "LAGGING", "opportunity": False,
         "current_exposure_pct": 2.0, "target_posture_pct": 8.0,
         "recommendation": "RESEARCH_FIRST"},
    ]
    uses = cp.build_capital_uses({}, [], opps, posture, 500_000.0)
    # only Energy: 1% gap of 500k = 5k
    assert uses["sector_rotation_usd"] == 5_000.0
    assert len(uses["sector_rotation"]) == 1
    assert uses["sector_rotation"][0]["sector"] == "Energy"


def test_uses_reserve_from_posture():
    posture = cp.cash_posture(100_000.0, 500_000.0, min_pct=20.0)
    uses = cp.build_capital_uses({}, [], [], posture, 500_000.0)
    assert uses["reserve"] == 100_000.0


# ─────────────────────────────────────────────────────────────────────────────
# Full plan envelope + arithmetic
# ─────────────────────────────────────────────────────────────────────────────

def test_build_capital_plan_required_fields():
    queue = {"items": [{"symbol": "V", "verdict": "TRIM", "source": "cio"},
                       {"symbol": "TSLA", "verdict": "ADD", "source": "advisory"}],
             "distinct_sources": 2}
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0, cash_total=100_000.0,
        positions=[
            {"symbol": "NVDA", "market_value": 60_000.0, "account": "schwab_taxable"},
            {"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"},
        ],
        queue=queue,
    )
    for field in ("as_of", "portfolio_value_usd", "cash_total_usd", "cash_reserved_usd",
                  "cash_investable_usd", "cash_policy_band", "capital_sources",
                  "capital_uses", "net_recommended_deploy_usd", "net_recommended_raise_usd",
                  "post_plan_cash_usd", "post_plan_cash_pct", "portfolio_constraints",
                  "alternatives", "position_decisions", "digest"):
        assert field in plan, field
    assert plan["authority"] == "READ_ONLY_ADVISORY"


def test_build_capital_plan_arithmetic_sums():
    # cash exactly at 20% floor → investable 0; deploy only from raised cash
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0, cash_total=100_000.0,
        positions=[
            {"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"},
        ],
        queue={"items": [{"symbol": "V", "verdict": "TRIM", "source": "cio"},
                         {"symbol": "TSLA", "verdict": "ADD", "source": "advisory"}]},
    )
    # trim V = 4k; add TSLA = 5k; deploy = min(5k, investable 0 + raise 4k) = 4k
    assert plan["capital_sources"]["total_raise_usd"] == 4_000.0
    assert plan["net_recommended_raise_usd"] == 4_000.0
    assert plan["net_recommended_deploy_usd"] == 4_000.0
    assert plan["post_plan_cash_usd"] == 100_000.0
    assert plan["post_plan_cash_pct"] == 20.0


def test_build_capital_plan_never_force_deploy():
    # lots of cash above band, but NO uses → deploy 0 (cash is not force-deployed)
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0, cash_total=200_000.0,
        positions=[{"symbol": "NVDA", "market_value": 60_000.0, "account": "schwab_taxable"}],
        queue=None,
    )
    assert plan["cash_investable_usd"] == 100_000.0  # 200k - 100k reserve
    assert plan["net_recommended_deploy_usd"] == 0.0
    assert plan["net_recommended_raise_usd"] == 0.0


def test_build_capital_plan_deploy_bounded_by_deployable():
    # huge deployment request, small cash + no raise → capped at deployable
    queue = {"items": [
        {"symbol": f"SYM{i}", "verdict": "ADD", "source": "advisory"} for i in range(10)
    ]}
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0, cash_total=110_000.0,
        positions=[{"symbol": "NVDA", "market_value": 60_000.0, "account": "schwab_taxable"}],
        queue=queue,
    )
    deployable = plan["cash_investable_usd"] + plan["capital_sources"]["total_raise_usd"]
    assert plan["net_recommended_deploy_usd"] == round(deployable, 2)
    # every ADD is a fresh symbol: headroom = 60k each, so request = 10 * 5k = 50k
    assert plan["capital_uses"]["total_deploy_request_usd"] == 50_000.0
    # cash 110k - reserve 100k = 10k investable; deploy capped at 10k
    assert plan["net_recommended_deploy_usd"] == 10_000.0


def test_build_capital_plan_digest_deterministic():
    args = dict(
        portfolio_value=500_000.0, cash_total=100_000.0,
        positions=[{"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"}],
        queue={"items": [{"symbol": "V", "verdict": "TRIM", "source": "cio"}]},
    )
    a = cp.build_capital_plan(**args)
    b = cp.build_capital_plan(**args)
    assert a["digest"] == b["digest"]
    # changing cash changes the digest
    c = cp.build_capital_plan(**{**args, "cash_total": 120_000.0})
    assert c["digest"] != a["digest"]


# ─────────────────────────────────────────────────────────────────────────────
# Alternatives
# ─────────────────────────────────────────────────────────────────────────────

def test_alternatives_do_nothing_always_present():
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0, cash_total=100_000.0, positions=[], queue=None)
    names = [a["name"] for a in plan["alternatives"]]
    assert "do_nothing" in names
    # no signals → high uncertainty → await_confluence present
    assert "await_confluence" in names


def test_alternatives_half_sized_when_deploying():
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0, cash_total=150_000.0,
        positions=[],
        queue={"items": [{"symbol": "TSLA", "verdict": "ADD", "source": "advisory"}],
               "distinct_sources": 2},
    )
    names = [a["name"] for a in plan["alternatives"]]
    assert "half_sized" in names
    half = next(a for a in plan["alternatives"] if a["name"] == "half_sized")
    assert half["deploy_usd"] == round(plan["net_recommended_deploy_usd"] * 0.5, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Position Decision table
# ─────────────────────────────────────────────────────────────────────────────

def test_position_decisions_delta_sign_and_tax():
    queue = {"items": [
        {"symbol": "V", "verdict": "EXIT", "source": "cio"},
        {"symbol": "NVDA", "verdict": "ADD", "source": "advisory"},
    ]}
    rows = cp.build_position_decisions(
        _positions(), queue=queue, portfolio_value=500_000.0)
    by = {r["symbol"]: r for r in rows}
    assert by["V"]["cio_stance"] == "EXIT"
    assert by["V"]["recommended_delta_usd"] == -40_000.0
    assert "release to cash" in by["V"]["funding"]
    # V is in a rollover_ira (name inference) → tax-advantaged, no lot drag
    assert "tax-advantaged" in by["V"]["tax_account_constraint"]
    # NVDA add, but NVDA is already at cap (60k = 12% of 500k) → headroom 0 → 0 delta
    assert by["NVDA"]["cio_stance"] == "ADD"
    assert by["NVDA"]["recommended_delta_usd"] == 0.0


def test_position_decisions_trim_delta():
    queue = {"items": [{"symbol": "V", "verdict": "TRIM", "source": "cio"}]}
    rows = cp.build_position_decisions(
        _positions(), queue=queue, portfolio_value=500_000.0)
    v = next(r for r in rows if r["symbol"] == "V")
    assert v["recommended_delta_usd"] == -4_000.0  # 10% of 40k


def test_position_decisions_hold_default():
    rows = cp.build_position_decisions(_positions(), queue=None, portfolio_value=500_000.0)
    assert all(r["cio_stance"] == "HOLD" for r in rows)
    assert all(r["recommended_delta_usd"] == 0.0 for r in rows)


def test_position_decisions_ordered_by_activity():
    queue = {"items": [{"symbol": "V", "verdict": "EXIT", "source": "cio"}]}
    rows = cp.build_position_decisions(
        _positions(), queue=queue, portfolio_value=500_000.0)
    # V (EXIT, -40k) sorts first (largest abs delta)
    assert rows[0]["symbol"] == "V"


def test_position_decisions_counter_thesis():
    rows = cp.build_position_decisions(
        _positions(), queue=None, portfolio_value=500_000.0,
        divergence_map={"NVDA": "analyst downgrade"})
    nvda = next(r for r in rows if r["symbol"] == "NVDA")
    assert nvda["counter_thesis"] == "analyst downgrade"
    v = next(r for r in rows if r["symbol"] == "V")
    assert v["counter_thesis"] == "no Street/desk disagreement on record"


# ─────────────────────────────────────────────────────────────────────────────
# Live reader / composition
# ─────────────────────────────────────────────────────────────────────────────

def test_load_holdings_snapshot():
    snap = cp.load_holdings_snapshot({
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 50_000.0, "account": "schwab_taxable"},
            {"symbol": "NVDA", "market_value": 60_000.0, "account": "schwab_taxable"},
        ],
        "portfolio_totals": {"total_value": 110_000.0},
        "config": {"accounts": {"schwab_taxable": {"taxable": True}}},
    })
    assert snap["portfolio_value"] == 110_000.0
    assert snap["cash_total"] == 50_000.0
    assert len(snap["positions"]) == 1
    assert snap["positions"][0]["symbol"] == "NVDA"


def test_load_holdings_snapshot_derives_total_from_holdings():
    snap = cp.load_holdings_snapshot({
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 10_000.0},
            {"symbol": "NVDA", "market_value": 90_000.0},
        ],
    })
    assert snap["portfolio_value"] == 100_000.0


def test_build_capital_plan_from_sources_fails_soft():
    plan = cp.build_capital_plan_from_sources(holdings_doc=None, queue=None)
    assert plan["portfolio_value_usd"] == 0.0
    assert plan["cash_total_usd"] == 0.0
    assert plan["net_recommended_deploy_usd"] == 0.0
    assert plan["digest"]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — double-count guard + cash ledger invariants
# ─────────────────────────────────────────────────────────────────────────────

def test_phase2_redeploy_not_double_counted_in_deployable():
    """Open redeploy remaining is already in cash; must not inflate deployable twice.

    Scenario mirrors Phase 0 live bug shape:
      cash 578k, earmark ~560k (inside cash), trim/exit raise ~63k
    Old: total_raise = 623k, deployable = investable + 623k  (double-count)
    New: total_raise = 63k,  deployable = investable + 63k
    """
    cash = 578_107.50
    value = 1_282_425.99
    # reserve at ~20% default ≈ 256485.20; investable ≈ 321622.30
    earmark = 560_009.02
    prospective = 63_000.0  # trims+exits only
    events = [{"event_id": 1, "symbol": "MATURE", "remaining_usd": earmark}]
    # One EXIT of 63k to create prospective raise without relying on trim math
    positions = [
        {"symbol": "EXITME", "market_value": prospective, "account": "schwab_rollover_ira"},
        {"symbol": "HOLD", "market_value": 100_000.0, "account": "schwab_taxable"},
    ]
    queue = {"items": [{"symbol": "EXITME", "verdict": "EXIT", "source": "cio"}]}
    plan = cp.build_capital_plan(
        portfolio_value=value, cash_total=cash,
        positions=positions, queue=queue, redeploy_open_events=events,
    )
    assert plan["plan_version"] == "capital_plan_1.1.0"
    assert plan["capital_sources"]["maturities_usd"] == earmark
    assert plan["capital_sources"]["earmarked_redeploy_usd"] == earmark
    assert plan["capital_sources"]["total_raise_usd"] == prospective
    assert plan["capital_sources"]["total_prospective_raise_usd"] == prospective
    assert plan["net_recommended_raise_usd"] == prospective
    # deployable must NOT be investable + earmark + prospective
    investable = plan["cash_investable_usd"]
    assert plan["deployable_usd"] == round(investable + prospective, 2)
    # Old buggy formula would have been investable + earmark + prospective
    old_buggy = round(investable + earmark + prospective, 2)
    assert plan["deployable_usd"] < old_buggy
    assert plan["cash_ledger"]["invariants_ok"] is True
    assert all(i["ok"] for i in plan["ledger_invariants"])


def test_phase2_cash_ledger_invariants():
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0, cash_total=150_000.0,
        positions=[{"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"}],
        queue={"items": [{"symbol": "V", "verdict": "TRIM", "source": "cio"},
                         {"symbol": "TSLA", "verdict": "ADD", "source": "advisory"}]},
        redeploy_open_events=[{"event_id": 1, "remaining_usd": 40_000.0}],
    )
    ledger = plan["cash_ledger"]
    assert ledger["settled_cash_usd"] == 150_000.0
    assert ledger["earmarked_redeploy_usd"] == 40_000.0
    assert ledger["free_unearmarked_usd"] == 110_000.0
    assert ledger["prospective_raise_usd"] == 4_000.0
    assert ledger["invariants_ok"] is True
    names = {i["name"] for i in ledger["invariants"]}
    assert names == {
        "earmark_le_cash",
        "investable_eq_cash_minus_reserve",
        "post_cash_identity",
        "deploy_le_investable_plus_prospective",
    }
    # post cash identity: cash + prospective - deploy
    assert abs(
        plan["post_plan_cash_usd"]
        - (plan["cash_total_usd"] + plan["net_recommended_raise_usd"]
           - plan["net_recommended_deploy_usd"])
    ) < 0.02


def test_phase2_account_cash_breakdown():
    rows = [
        {"symbol": "CASH", "is_cash": True, "market_value": 500.0, "account": "moomoo"},
        {"symbol": "CASH", "is_cash": True, "market_value": 37_894.31, "account": "schwab_taxable"},
        {"symbol": "NVDA", "market_value": 10_000.0, "account": "schwab_taxable"},
    ]
    ac = cp.account_cash_breakdown(rows)
    assert ac == [
        {"account": "moomoo", "settled_cash_usd": 500.0},
        {"account": "schwab_taxable", "settled_cash_usd": 37_894.31},
    ]


def test_phase2_live_shape_578k_regeneration():
    """First-principles regen of Phase 0 reported cash layers (no DB).

    Phase 0 live report (buggy v1.0.0):
      cash 578107.50, reserved 256485.20, investable 321622.30,
      raise 623009.02 (included maturities), deploy 603114.70

    Correct v1.1.0 with earmark 560009.02 and prospective 63000:
      raise = 63000 only; deployable = investable + 63000 (not +560k again)
    """
    cash = 578_107.50
    value = 1_282_425.99  # cash + equities shape from Phase 0
    reserved = round(value * 20.0 / 100.0, 2)  # default 20% band
    investable = round(max(0.0, cash - reserved), 2)
    assert reserved == 256_485.20
    assert investable == 321_622.30

    earmark = 560_009.02
    prospective = 63_000.0  # 623009.02 - 560009.02 from Phase 0 fixtures
    events = [{"event_id": 1, "symbol": "REDEPLOY", "remaining_usd": earmark}]
    positions = [
        {"symbol": "EXITME", "market_value": prospective, "account": "schwab_rollover_ira"},
    ]
    # Large deploy request to surface deployable cap (not force-deploy)
    queue = {"items": [
        {"symbol": "EXITME", "verdict": "EXIT", "source": "cio"},
        *[{"symbol": f"ADD{i}", "verdict": "ADD", "source": "advisory"} for i in range(80)],
    ]}
    plan = cp.build_capital_plan(
        portfolio_value=value, cash_total=cash,
        positions=positions, queue=queue, redeploy_open_events=events,
        account_cash=[
            {"account": "moomoo_taxable_live", "settled_cash_usd": 500.0},
            {"account": "alpaca_taxable_live", "settled_cash_usd": 5_000.0},
            {"account": "schwab_taxable", "settled_cash_usd": 37_894.31},
            {"account": "schwab_roth", "settled_cash_usd": 1_469.22},
            {"account": "schwab_rollover_ira", "settled_cash_usd": 533_243.97},
        ],
    )
    assert plan["cash_total_usd"] == cash
    assert plan["cash_reserved_usd"] == reserved
    assert plan["cash_investable_usd"] == investable
    assert plan["cash_earmarked_redeploy_usd"] == earmark
    assert plan["net_recommended_raise_usd"] == prospective
    # Correct deployable (NOT 321622 + 623009)
    assert plan["deployable_usd"] == round(investable + prospective, 2)
    assert plan["deployable_usd"] == 384_622.30
    # Old buggy deployable would be ~944k
    old_buggy_deployable = round(investable + earmark + prospective, 2)
    assert old_buggy_deployable == 944_631.32
    assert plan["net_recommended_deploy_usd"] <= plan["deployable_usd"] + 0.02
    assert plan["cash_ledger"]["invariants_ok"] is True
    # Account cash sums to settled cash
    assert abs(sum(a["settled_cash_usd"] for a in plan["cash_ledger"]["account_cash"]) - cash) < 0.02
