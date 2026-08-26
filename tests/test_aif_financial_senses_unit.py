"""Unit tests for the AIF ↔ Financial Senses governed adapter."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.agent_context_envelope import build_context_envelope, validate_context_envelope
from scripts.lib.agent_context_integration import apply_context_budget
from scripts.lib.agent_feature_flags import (
    activation_scope_check,
    load_feature_flags,
    rollback_flags,
)
from scripts.lib.financial_senses.result import (
    AUTHORITY,
    Fact,
    FinancialSenseResult,
    ModelEstimate,
    Quality,
    STATUS_OK,
)
from scripts.lib.financial_senses.source_governance import SOURCE_MODEL_INFERENCE, SOURCE_PRIMARY_REGULATORY
from scripts.lib.financial_senses_aif import (
    FLAG_AIF_FINANCIAL_SENSES_SHADOW,
    INTENTIONALLY_UNEXPOSED,
    aif_exposed_tool_names,
    aif_validate_result,
    attach_to_envelope,
    behavior_influence,
    build_fixture_providers,
    empty_financial_senses_section,
    invoke_capability,
    is_fresh_current_evidence,
    manifest_drift,
    memory_behavior_influence,
    reject_raw_memory_admission,
    result_to_aif_payload,
    shadow_enabled,
)
from scripts.lib.mcp_read_only_gateway import ALLOWED_TOOLS, classify_tool_allowed


def test_manifest_has_no_drift():
    assert manifest_drift() == []
    assert "openbb" in INTENTIONALLY_UNEXPOSED


def test_all_exposed_tools_are_allowlisted_and_read_only():
    names = aif_exposed_tool_names()
    assert names
    for name in names:
        ok, reason = classify_tool_allowed(name)
        assert ok, (name, reason)
        assert ALLOWED_TOOLS[name] in {
            "sec_edgar", "macro", "identity", "stress", "evidence", "factor", "critic",
        }


def test_no_write_tool_registered():
    for name in aif_exposed_tool_names():
        assert "write" not in name
        assert classify_tool_allowed(f"{name}.write")[0] is False


def test_flags_default_off():
    flags = load_feature_flags({})
    assert flags[FLAG_AIF_FINANCIAL_SENSES_SHADOW] == 0
    assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == 0
    assert shadow_enabled({}) is False
    assert behavior_influence() is False
    assert memory_behavior_influence({}) == 0
    rb = rollback_flags()
    assert rb[FLAG_AIF_FINANCIAL_SENSES_SHADOW] == 0
    assert rb["MEMORY_BEHAVIOR_INFLUENCE"] == 0


def test_shadow_flag_on():
    assert shadow_enabled({FLAG_AIF_FINANCIAL_SENSES_SHADOW: "1"}) is True
    assert shadow_enabled({FLAG_AIF_FINANCIAL_SENSES_SHADOW: "yes"}) is True
    assert shadow_enabled({FLAG_AIF_FINANCIAL_SENSES_SHADOW: "maybe"}) is False


def test_activation_scope_denies_behavior():
    ok, _ = activation_scope_check("financial senses behavior influence")
    assert ok is False
    ok, _ = activation_scope_check("financial senses broker")
    assert ok is False
    ok, _ = activation_scope_check("financial senses informs analysis")
    assert ok is True


def test_freshness_only_explicit_fresh_counts():
    assert is_fresh_current_evidence("FRESH") is True
    assert is_fresh_current_evidence("fresh") is True
    assert is_fresh_current_evidence("STALE") is False
    assert is_fresh_current_evidence("UNKNOWN") is False
    assert is_fresh_current_evidence(None) is False
    assert is_fresh_current_evidence("") is False
    assert is_fresh_current_evidence("YESTERDAY") is False


def test_invalid_quality_rejected():
    r = FinancialSenseResult(provider="sec_edgar", capability="sec.resolve_cik", status=STATUS_OK)
    r.authority = AUTHORITY
    r.quality = Quality(grade="HIGH_CONFIDENCE", freshness="FRESH")
    r.facts.append(
        Fact(
            key="cik",
            value="1",
            source_type=SOURCE_PRIMARY_REGULATORY,
            as_of="2026-08-17",
            quality="HIGH_CONFIDENCE",
        )
    )
    errors = aif_validate_result(r)
    assert errors
    assert any("quality" in e.lower() for e in errors)


def test_model_estimate_cannot_become_fact():
    r = FinancialSenseResult(provider="critic", capability="critic.review", status=STATUS_OK)
    r.facts.append(
        Fact(
            key="fake",
            value=1,
            source_type=SOURCE_MODEL_INFERENCE,
            as_of="2026-08-17",
            quality="HIGH",
        )
    )
    errors = aif_validate_result(r)
    assert errors
    payload = result_to_aif_payload(r, validation=errors)
    assert payload["financial_senses"]["validation_ok"] is False
    assert payload["financial_senses"]["authoritative_facts"] == []


def test_stale_fact_is_not_current_support():
    r = FinancialSenseResult(provider="sec_edgar", capability="sec.resolve_cik", status=STATUS_OK)
    r.quality = Quality(grade="HIGH", freshness="STALE")
    r.facts.append(
        Fact(
            key="cik",
            value="0000320193",
            source_type=SOURCE_PRIMARY_REGULATORY,
            as_of="2020-01-01",
            quality="HIGH",
            freshness="STALE",
        )
    )
    payload = result_to_aif_payload(r)
    facts = payload["financial_senses"]["facts"]
    assert facts[0]["is_current_authoritative_support"] is False
    assert "not FRESH" in facts[0]["current_evidence_warning"]


def test_invoke_resolve_cik_fixture():
    providers = build_fixture_providers()
    result = invoke_capability("sec.resolve_cik", {"symbol": "AAPL"}, providers=providers)
    assert result.provider == "sec_edgar"
    assert result.capability == "sec.resolve_cik"
    assert result.authority == AUTHORITY
    assert result.data.get("cik") == "0000320193"
    payload = result_to_aif_payload(result)
    assert payload["behavior_influence"] is False
    assert payload["shadow_only"] is True
    assert payload["financial_senses"]["request_id"]


def test_not_configured_openfigi_without_key():
    from scripts.lib.financial_senses.identity import OpenFigiProvider

    result = invoke_capability(
        "identity.resolve",
        {"ticker": "AAPL"},
        providers={"identity": OpenFigiProvider()},
    )
    assert result.status == "NOT_CONFIGURED"


def test_unknown_tool_invalid():
    r = invoke_capability("sec.place_order", {"symbol": "AAPL"}, providers=build_fixture_providers())
    assert r.status == "INVALID_REQUEST"


def test_forbidden_request_fields_rejected():
    r = invoke_capability(
        "sec.resolve_cik",
        {"symbol": "AAPL", "authoritative": True},
        providers=build_fixture_providers(),
    )
    assert r.status == "INVALID_REQUEST"
    assert any("forbidden" in w for w in r.warnings)


def test_context_envelope_preserves_structure():
    env = build_context_envelope(agent="alex", role="cio", wake_id="w1", trace_id="t1")
    ok, errors = validate_context_envelope(env)
    assert ok, errors
    fs = env["specialist_context"]["financial_senses"]
    assert fs["behavior_influence"] is False
    assert fs["shadow_only"] is True
    result = invoke_capability("sec.resolve_cik", {"symbol": "AAPL"}, providers=build_fixture_providers())
    env2 = attach_to_envelope(env, [result_to_aif_payload(result)])
    item = env2["specialist_context"]["financial_senses"]["items"][0]
    assert item["provider"] == "sec_edgar"
    assert item["capability"] == "sec.resolve_cik"
    assert item["request_id"]
    assert "quality" in item
    assert "freshness" in item
    assert item["behavior_influence"] is False
    ok, errors = validate_context_envelope(env2)
    assert ok, errors


def test_budget_drops_fs_not_office_truth():
    env = build_context_envelope(
        agent="alex",
        role="cio",
        wake_id="w1",
        trace_id="t1",
        office_truth={"holdings_ref": "HOLD", "cash_ref": "CASH", "source_asof": "2026-08-17"},
        decision={"current_action": "HOLD", "act_now": False},
    )
    result = invoke_capability("sec.resolve_cik", {"symbol": "AAPL"}, providers=build_fixture_providers())
    payload = result_to_aif_payload(result)
    payload["financial_senses"]["data"] = {"pad": "x" * 8000}
    env = attach_to_envelope(env, [payload])
    budgeted, meta = apply_context_budget(env, budget_tokens=40)
    assert meta["canonical_truth_preserved"] is True
    assert budgeted["office_truth"]["holdings_ref"] == "HOLD"
    fs = budgeted["specialist_context"]["financial_senses"]
    assert fs["behavior_influence"] is False
    assert fs["shadow_only"] is True
    # Either items dropped or budget still within — truth must remain.
    assert not isinstance(budgeted.get("office_truth"), dict) or budgeted["office_truth"].get("budget_truncated") is not True


def test_memory_rejects_raw_fs():
    ok, reason = reject_raw_memory_admission({"financial_senses": {"facts": []}})
    assert ok is False
    assert "not durable memory" in reason
    ok, _ = reject_raw_memory_admission({"note": "operator said wait"})
    assert ok is True


def test_empty_section_contract():
    s = empty_financial_senses_section()
    assert s["behavior_influence"] is False
    assert s["shadow_only"] is True
    assert s["items"] == []
