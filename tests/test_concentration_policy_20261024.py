"""Operator Addendum3: one policy, measured classes, exact boundaries, no broker."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from scripts.lib import ips_policy as policy
from scripts.lib.data_broker import opportunity

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)


def fund(**kw):
    return {"is_fund": True, "is_leveraged": False, "is_inverse": False,
            "coverage_complete": True, "holding_count": 103, "largest_holding_pct": 6.7,
            "top10_weight_pct": 44, "source": "fixture complete fund statement", "as_of": NOW.isoformat(), **kw}


def assess(weight, *, evidence=None, kind="ETF", **kw):
    return policy.concentration_for_position({"asset_type": kind}, weight_pct=weight,
                                             evidence=evidence, **kw)


def test_one_approved_key_and_no_legacy_threshold_copies():
    doc = json.loads((ROOT / "config/investment_policy_statement.json").read_text())
    c = doc["constraints"]
    assert all(k not in c for k in ("max_single_position_pct", "critical_single_position_pct", "max_sector_concentration_pct"))
    result = policy.concentration_policy()
    assert result["approval_ref"] == "operator-2026-10-24-Addendum3-R13"
    assert {r["id"]: r["limit_pct"] for r in result["classes"]} == {
        "broad_diversified_fund": 25, "narrow_thematic_fund": 12, "single_stock": 12, "leveraged_inverse_fund": 5}
    assert result["lookthrough_company_limit_pct"] == 12 and result["lookthrough_sector_limit_pct"] == 25
    assert result["near_limit_fraction"] == .9


@pytest.mark.parametrize("weight,status", [(16.8,"ok"),(22.5,"near_limit"),(23,"near_limit"),(25,"near_limit"),(25.001,"breach")])
def test_broad_fund_uses_its_own_limit(weight, status):
    result = assess(weight, evidence=fund())
    assert result["classification"] == "broad_diversified_fund"
    assert result["limit_pct"] == 25 and result["status"] == status


@pytest.mark.parametrize("weight,status", [(10,"ok"),(10.8,"near_limit"),(12,"near_limit"),(12.001,"breach"),(22.6,"breach")])
def test_stock_limit_has_exact_breach_and_near_boundaries(weight, status):
    result = assess(weight, kind="stock")
    assert result["limit_pct"] == 12 and result["status"] == status


@pytest.mark.parametrize("count,largest,top10,expected", [
    (29,6,40,"narrow_thematic_fund"),(30,6,40,"narrow_thematic_fund"),
    (49,6,40,"narrow_thematic_fund"),(50,9.99,50,"broad_diversified_fund"),
    (100,9,50.001,"narrow_thematic_fund"),(100,11,67,"narrow_thematic_fund"),
    (50,10,40,None),
])
def test_measured_fund_classification_thresholds(count, largest, top10, expected):
    result = assess(16.8, evidence=fund(holding_count=count, largest_holding_pct=largest, top10_weight_pct=top10))
    assert result["classification"] == expected
    assert bool(result["gap"]) is (expected is None)


@pytest.mark.parametrize("field", ["is_leveraged","is_inverse"])
def test_leveraged_or_inverse_metadata_uses_the_approved_cap(field):
    result = assess(5.1, evidence=fund(**{field: True, "coverage_complete": False}))
    assert result["classification"] == "leveraged_inverse_fund" and result["limit_pct"] == 5
    assert result["status"] == "breach"


@pytest.mark.parametrize("bad", [
    {"sample_only": True}, {"coverage_complete": False}, {"coverage_complete": "false"},
    {"holding_count": None}, {"as_of": None}, {"is_leveraged": None},
    {"largest_holding_pct": 50, "top10_weight_pct": 20},
])
def test_missing_or_sample_evidence_never_becomes_a_broad_class(bad):
    result = assess(16.8, evidence=fund(**bad))
    assert result["classification"] is None and result["limit_pct"] is None
    assert result["status"] == "unknown" and result["gap"]


def test_ten_cache_rows_are_not_a_fund_holding_count():
    result = assess(16.8, evidence={"holdings": [{"symbol": str(i)} for i in range(10)], "source": "top10 cache"})
    assert result["limit_pct"] is None and result["gap"]


def test_missing_policy_is_unknown_without_a_hardcoded_fallback(tmp_path):
    result = policy.concentration_policy(tmp_path)
    assert result["gap"] and all(r["limit_pct"] is None for r in result["classes"])
    assert policy.ips_max_position_pct(tmp_path) is None


@pytest.mark.parametrize("raw", [[], {"limits_pct": []}, {"limits_pct": "invalid"}])
def test_malformed_policy_is_an_explicit_gap(tmp_path, raw):
    (tmp_path / policy.IPS_FILENAME).write_text(json.dumps({"constraints": {"concentration_policy": raw}}))
    assert policy.concentration_policy(tmp_path)["gap"]
    assert policy.ips_max_position_pct(tmp_path) is None


def test_midrange_operator_classification_requires_a_dated_approval():
    evidence = fund(holding_count=40)
    assert assess(16.8, evidence=evidence)["limit_pct"] == 12
    evidence["operator_classification"] = {"classification": "broad_diversified_fund",
        "approval_ref": "fixture operator decision", "source": "fixture recorded decision", "as_of": NOW.isoformat()}
    result = assess(16.8, evidence=evidence)
    assert result["limit_pct"] == 25 and result["operator_classification"]["approval_ref"]
    evidence["operator_classification"].pop("approval_ref")
    assert assess(16.8, evidence=evidence)["status"] == "unknown"


def test_policy_value_change_flows_through_the_same_reader(tmp_path):
    doc = json.loads((ROOT / "config/investment_policy_statement.json").read_text())
    doc["constraints"]["concentration_policy"]["limits_pct"]["broad_diversified_fund"] = 30
    (tmp_path / policy.IPS_FILENAME).write_text(json.dumps(doc))
    result = assess(26, evidence=fund(), config_dir=tmp_path)
    assert result["limit_pct"] == 30 and result["status"] == "ok"


def test_explicit_fixture_policy_path_is_respected(tmp_path):
    path = tmp_path / "captured-ips.json"
    path.write_text(json.dumps({"constraints": {"max_single_position_pct": 8}}))
    assert policy.ips_max_position_pct(path) == 8


def test_curator_stops_universal_trim_for_broad_fund_and_marks_missing_evidence():
    ctx = {"position": {"owned": True, "weight_pct": 16.8, "asset_type": "ETF"},
           "fund_holdings_evidence": fund()}
    result = opportunity.classify(ctx, 60, {"rr": 1}, coverage=1)
    assert result["stance"] == "HOLD" and result["concentration_policy"]["limit_pct"] == 25
    ctx["fund_holdings_evidence"] = {}
    result = opportunity.classify(ctx, 60, {"rr": 1}, coverage=1)
    assert result["stance"] != "TRIM" and result["concentration_policy"]["gap"]
    ctx["position"]["asset_type"] = "stock"
    assert opportunity.classify(ctx, 60, {"rr": 1}, coverage=1)["stance"] == "TRIM"


def test_display_and_engine_get_same_whole_book_guid_policy_without_mutation():
    doc = {"portfolio": {"total_usd": 1000000}, "positions": {
        "rows": [{"security_guid": "g", "symbol": "SCHD", "asset_type": "ETF", "market_value": 100000},
                 {"security_guid": "g", "symbol": "SCHD", "asset_type": "ETF", "market_value": 68000}],
        "concentration": [{"symbol": "SCHD", "pct": 16.8}], "largest_name": {"symbol": "SCHD", "pct": 16.8}},
        "capital": {"alert_level_pct": 16.5}}
    before = deepcopy(doc)
    result = policy.apply_concentration(doc, evidence_by_guid={"g": fund()})
    row = result["positions"]["concentration"][0]
    engine = policy.policy_for_security("g", document=doc, fund_evidence=fund())
    assert row["limit_pct"] == engine["limit_pct"] == 25
    assert row["weight_pct"] == engine["weight_pct"] == 16.8
    assert row["status"] == "ok" and result["capital"]["alert_level_pct"] is None
    assert before == doc


def test_disagreeing_account_instrument_facts_do_not_pick_one_class():
    doc = {"portfolio": {"total_usd": 100}, "positions": {"rows": [
        {"security_guid": "g", "market_value": 5, "asset_type": "stock"},
        {"security_guid": "g", "market_value": 5, "asset_type": "ETF"}]}}
    assert policy.policy_for_security("g", document=doc)["status"] == "unknown"
    assert policy.policy_for_security("different-guid", document=doc)["weight_pct"] is None


def test_named_risk_default_reads_ips_and_preserves_safe_float(monkeypatch):
    import risk_gate
    from lib import ips_policy as gate_policy
    monkeypatch.setattr(gate_policy, "ips_max_position_pct", lambda: 21)
    assert risk_gate.concentration_default_fraction() == .21
    monkeypatch.setattr(gate_policy, "ips_max_position_pct", lambda: None)
    assert risk_gate.concentration_default_fraction() is None
    assert risk_gate._safe_float({"value": 3}) == 3
    assert risk_gate._safe_float(2) == 2
