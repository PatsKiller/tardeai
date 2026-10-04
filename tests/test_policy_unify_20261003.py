"""Operator 2026-10-03: the ratified investment policy drives cash and sizing.

Before, the capital plan sized from the desk thesis (20% cash floor, $252,827
reserve) while the ratified policy said 2-15% and a $75,000 reserve. Now the
ratified value wins, a missing one falls back to the thesis with a label, and a
thesis that disagrees is recorded as a proposal, never applied.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_capital_plan as cp  # noqa: E402
from scripts.lib.cio_operator_investment_policy import (  # noqa: E402
    FIELD_SPECS,
    build_operator_investment_policy,
    ratify_policy_field,
)

THESIS = {"cash_band_min_pct": 20.0, "max_single_name_weight_pct": 12.0, "concentration_fire_pct": 16.5}


def _policy(**confirmed):
    return {"fields": {name: {"value": value, "operator_confirmed": True} for name, value in confirmed.items()}}


def _plan(policy=None, **kw):
    return cp.build_capital_plan(portfolio_value=1_000_000.0, cash_total=600_000.0, positions=[],
                                 risk_posture=THESIS, investment_policy=policy, **kw)


def test_ratified_cash_band_and_reserve_drive_the_plan():
    plan = _plan(_policy(cash_target_range_pct={"min": 2.0, "max": 15.0}, minimum_liquidity_reserve_usd=75_000))
    assert plan["cash_policy_band"]["min_pct"] == 2.0 and plan["cash_policy_band"]["max_pct"] == 15.0
    assert plan["cash_reserved_usd"] == 75_000.0  # absolute reserve outranks the 2% ($20,000) floor
    src = plan["sizing_policy"]["policy_source"]
    assert src["cash_band_min_pct"] == "ratified" and src["reserve_floor_usd"] == "ratified"


def test_unratified_fields_fall_back_to_the_thesis_with_a_label():
    plan = _plan(_policy())
    assert plan["cash_reserved_usd"] == 200_000.0
    src = plan["sizing_policy"]["policy_source"]
    assert src["cash_band_min_pct"] == "desk_thesis_fallback"
    assert src["max_single_name_pct"] == "desk_thesis_fallback"
    assert src["reserve_floor_usd"] == "none"


def test_a_disagreeing_thesis_is_recorded_not_applied():
    plan = _plan(_policy(cash_target_range_pct={"min": 2.0, "max": 15.0}))
    assert plan["cash_policy_band"]["min_pct"] == 2.0
    proposals = plan["sizing_policy"]["thesis_proposed_changes"]
    assert proposals == [{"field": "cash_band_min_pct", "ratified": 2.0, "thesis_proposed": 20.0,
                          "status": "PROPOSED_NOT_APPLIED"}]


def test_ratified_twelve_percent_cap_is_used_and_labelled():
    plan = _plan(_policy(concentration_hierarchy={"max_single_position_pct": 12.0}))
    assert plan["sizing_policy"]["max_single_name_pct"] == 12.0
    assert plan["sizing_policy"]["policy_source"]["max_single_name_pct"] == "ratified"
    assert plan["sizing_policy"]["policy_source"]["concentration_fire_pct"] == "desk_thesis_fallback"


def test_explicit_arguments_still_win_and_say_so():
    plan = _plan(_policy(cash_target_range_pct={"min": 2.0, "max": 15.0}), cash_band_min_pct=10.0)
    assert plan["cash_policy_band"]["min_pct"] == 10.0
    assert plan["sizing_policy"]["policy_source"]["cash_band_min_pct"] == "explicit_argument"


def test_confirmed_needs_only_the_fields_code_reads(tmp_path):
    required = {n for n, s in FIELD_SPECS.items() if s["required"]}
    assert required == {"cash_target_range_pct", "minimum_liquidity_reserve_usd", "equity_range_pct",
                        "fixed_income_range_pct", "alternatives_range_pct", "concentration_hierarchy"}
    store = str(tmp_path / "profile.jsonl")
    values = {"cash_target_range_pct": {"min": 2, "max": 15}, "minimum_liquidity_reserve_usd": 75000,
              "equity_range_pct": {"min": 20, "max": 80}, "fixed_income_range_pct": {"min": 0, "max": 20},
              "alternatives_range_pct": {"min": 0, "max": 15},
              "concentration_hierarchy": {"max_single_position_pct": 12}}
    for name, value in values.items():
        ratify_policy_field(name, value, store_path=store)
    policy = build_operator_investment_policy(store_path=store, repo_root=ROOT)
    assert policy["status"] == "CONFIRMED"
    assert policy["confirmed_field_count"] == policy["required_field_count"] == 6
    assert "growth_objective" in policy["optional_missing_fields"]


def test_twelve_percent_is_consistent_everywhere():
    ips = json.loads((ROOT / "config" / "investment_policy_statement.json").read_text())
    assert ips["constraints"]["max_single_position_pct"] == 12.0
    desk = (ROOT / "config" / "advisory_desk.yaml").read_text()
    assert re.search(r"max single position\s+12%", desk)
    assert cp.MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT == 12.0
    proposal = json.loads((ROOT / "config" / "policy_proposals" / "operator_policy_proposal_20261003.json").read_text())
    conc = next(f for f in proposal["fields"] if f["field"] == "concentration_hierarchy")
    assert conc["value"]["max_single_position_pct"] == 12.0


def test_proposal_script_dry_run_writes_nothing(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("apply_prop", ROOT / "scripts" / "apply_operator_policy_proposal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    store = tmp_path / "profile.jsonl"
    assert mod.main(["--store", str(store)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is False and {f["field"] for f in out["fields"]} >= {"concentration_hierarchy"}
    assert not store.exists() or store.read_text() == ""
