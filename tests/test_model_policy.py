"""Unit tests for scripts/lib/model_policy.py — off-peak, urgent, model identity."""

from __future__ import annotations

import pytest

from scripts.lib.llm_model_registry import RegistryError
from scripts.lib.model_policy import (
    DEFAULT_OFFPEAK_PROPOSAL,
    assert_critic_provider_separated,
    default_l3_policy,
    evaluate_offpeak_eligibility,
    evaluate_urgent_materiality,
    forbid_local_author_substitute,
    resolve_author_model,
    validate_returned_model,
)
from tests.helpers.l3_fixtures import (
    DEFERRED_SUMMER_ET,
    OFFICIAL_PEAK_UTC,
    OFFPEAK_SUMMER_ET,
    OFFPEAK_WINTER_ET,
    make_grounded_input,
)


def test_default_policy_author_is_deepseek_flash():
    policy = default_l3_policy()
    binding = resolve_author_model(policy)
    assert binding["provider"] == "deepseek"
    assert binding["model_id"] == "deepseek-flash"
    assert policy.critic_provider != policy.author_provider


def test_offpeak_summer_edT_eligible_and_deferred():
    ok = evaluate_offpeak_eligibility(OFFPEAK_SUMMER_ET)
    assert ok.eligible is True
    assert ok.reason == "offpeak_bulk_window"
    deferred = evaluate_offpeak_eligibility(DEFERRED_SUMMER_ET)
    assert deferred.eligible is False
    assert deferred.reason == "outside_operator_bulk_et"


def test_offpeak_winter_est_eligible():
    ok = evaluate_offpeak_eligibility(OFFPEAK_WINTER_ET)
    assert ok.eligible is True
    assert ok.in_bulk_et is True


def test_official_utc_peak_weekday_not_eligible():
    d = evaluate_offpeak_eligibility(OFFICIAL_PEAK_UTC)
    assert d.eligible is False
    assert d.in_official_peak_utc is True
    assert d.reason == "official_deepseek_peak_utc"


def test_urgent_materiality_allowlist_not_prose():
    prose = make_grounded_input(materiality_basis="")
    prose["material_residual_question"]["urgency_prose"] = "please rush this"
    ok, reasons = evaluate_urgent_materiality(prose)
    assert ok is False
    assert any("allowlist" in r or "prose" in r for r in reasons)

    allow = make_grounded_input(
        materiality_basis="earnings_within_horizon",
        resolution_confidence=0.85,
    )
    ok2, reasons2 = evaluate_urgent_materiality(allow)
    assert ok2 is True
    assert reasons2 == []


def test_returned_model_mismatch_fails_closed():
    # Legacy DeepSeek IDs fail closed before the equality check.
    with pytest.raises(RegistryError, match="legacy DeepSeek model id rejected"):
        validate_returned_model(
            requested_model="deepseek-flash",
            returned_model="deepseek-chat",
            provider="deepseek",
        )
    # Non-DeepSeek provider path exercises explicit requested≠returned mismatch.
    with pytest.raises(RegistryError, match="model_mismatch"):
        validate_returned_model(
            requested_model="grok-3",
            returned_model="grok-3-mini",
            provider="grok",
        )


def test_returned_model_missing_fails():
    with pytest.raises(RegistryError, match="returned_model_missing"):
        validate_returned_model(
            requested_model="deepseek-flash",
            returned_model=None,
            provider="deepseek",
        )


def test_critic_provider_must_differ():
    with pytest.raises(RegistryError, match="author_critic_same_provider"):
        assert_critic_provider_separated("deepseek", "deepseek")
    assert_critic_provider_separated("deepseek", "grok")


def test_local_author_substitute_forbidden():
    with pytest.raises(RegistryError, match="local_model_forbidden"):
        forbid_local_author_substitute("ollama")


def test_proposed_offpeak_config_schema():
    assert DEFAULT_OFFPEAK_PROPOSAL["schema"] == "L3OffPeakPolicy@v1"
    assert DEFAULT_OFFPEAK_PROPOSAL["timezone"] == "America/New_York"
    bases = DEFAULT_OFFPEAK_PROPOSAL["urgent_exception"]["materiality_basis_allowlist"]
    assert "price_move_gt_threshold" in bases
