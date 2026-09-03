"""Fail-closed eligibility policy tests (fixture negative controls)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.research_observation import (
    SCHEMA_VERSION,
    EligibilityDecision,
    EntitlementStatus,
    FallbackState,
    FreshnessStatus,
    QualityStatus,
    evaluate_eligibility,
    make_research_observation,
)

NOW = datetime(2026, 9, 2, 18, 30, 0, tzinfo=timezone.utc)
T0 = "2026-09-02T18:00:00+00:00"
T1 = "2026-09-02T18:00:05+00:00"
T2 = "2026-09-02T18:00:06+00:00"


def _fresh(**overrides):
    base = dict(
        source_identity="hermes_research_results",
        provider="hermes_worker",
        freshness_status=FreshnessStatus.FRESH,
        quality_status=QualityStatus.OK,
        entitlement_status=EntitlementStatus.INTERNAL,
        provider_at=T0,
        observed_at=T0,
        received_at=T1,
        normalized_at=T2,
        run_id="run-ok",
        trace_id="trace:run-ok",
        sequence_or_version="1",
        calculation_or_model_version="model@v1",
        freshness_age_seconds=1800.0,
        durable_output_present=True,
        log_success_claimed=True,
        payload={"ok": True},
        fallback_state=FallbackState.NONE,
    )
    base.update(overrides)
    return make_research_observation(**base)


def test_fresh_eligible_accepted():
    obs = _fresh()
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert result.eligible
    assert result.decision is EligibilityDecision.ELIGIBLE
    assert "ALL_GATES_PASSED" in result.reasons


def test_stale_status_fail_closed():
    obs = _fresh(freshness_status=FreshnessStatus.STALE, freshness_age_seconds=200_000.0)
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any(r.startswith("FRESHNESS_BLOCK:STALE") for r in result.reasons)


def test_stale_age_fail_closed():
    obs = _fresh(freshness_age_seconds=200_000.0)
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any(r.startswith("STALE_AGE:") for r in result.reasons)


def test_gap_never_eligible():
    obs = _fresh(freshness_status=FreshnessStatus.GAP, durable_output_present=False)
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any("GAP" in r for r in result.reasons)


def test_no_data_never_eligible():
    obs = _fresh(
        freshness_status=FreshnessStatus.NO_DATA,
        durable_output_present=False,
        provider_at=None,
        observed_at=None,
    )
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="agent")
    assert not result.eligible


def test_missing_output_fail_closed():
    obs = _fresh(durable_output_present=False, freshness_status=FreshnessStatus.PARTIAL)
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any("DURABLE_OUTPUT" in r or "FRESHNESS_BLOCK" in r for r in result.reasons)


def test_log_only_success_fail_closed():
    obs = _fresh(durable_output_present=False, log_success_claimed=True, freshness_status=FreshnessStatus.ERROR)
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert "LOG_ONLY_SUCCESS_WITHOUT_DURABLE_OUTPUT" in result.reasons


def test_wrong_run_id():
    obs = _fresh()
    result = evaluate_eligibility(obs, now=NOW, expected_run_id="run-other", consumer_kind="proposal")
    assert not result.eligible
    assert any(r.startswith("WRONG_RUN_ID") for r in result.reasons)


def test_wrong_source_hash():
    obs = _fresh()
    result = evaluate_eligibility(obs, now=NOW, expected_source_hash="0" * 64, consumer_kind="proposal")
    assert not result.eligible
    assert any(r.startswith("WRONG_SOURCE_HASH") for r in result.reasons)


def test_missing_provenance():
    obs = _fresh(
        provider_at=None,
        observed_at=None,
        received_at=None,
        normalized_at=None,
        sequence_or_version=None,
        calculation_or_model_version=None,
        run_id="",
        trace_id="",
    )
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any(r.startswith("MISSING_PROVENANCE") for r in result.reasons)


def test_unknown_entitlement_fail_closed():
    obs = _fresh(entitlement_status=EntitlementStatus.UNKNOWN)
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any(r.startswith("ENTITLEMENT_BLOCK:UNKNOWN") for r in result.reasons)


def test_quality_failure_fail_closed():
    obs = _fresh(quality_status=QualityStatus.FAILED)
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="agent")
    assert not result.eligible
    assert any(r.startswith("QUALITY_FAILURE") for r in result.reasons)


def test_fallback_silent_forbidden():
    obs = _fresh(fallback_state=FallbackState.SILENT_FORBIDDEN)
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert "SILENT_FALLBACK_FORBIDDEN" in result.reasons


def test_clock_regression():
    # provider_at after received_at beyond skew
    obs = _fresh(
        provider_at="2026-09-02T19:00:00+00:00",
        received_at="2026-09-02T18:00:00+00:00",
        normalized_at="2026-09-02T18:00:01+00:00",
    )
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any("CLOCK_REGRESSION" in r for r in result.reasons)


def test_future_skew():
    obs = _fresh(
        provider_at="2026-09-02T20:00:00+00:00",
        observed_at="2026-09-02T20:00:00+00:00",
        received_at="2026-09-02T20:00:05+00:00",
        normalized_at="2026-09-02T20:00:06+00:00",
    )
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any(r.startswith("FUTURE_SKEW") for r in result.reasons)


def test_schema_version_mismatch():
    obs = _fresh(schema_version="ResearchObservation@v0")
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="proposal")
    assert not result.eligible
    assert any(r.startswith("SCHEMA_VERSION_MISMATCH") for r in result.reasons)
    assert obs.schema_version != SCHEMA_VERSION


def test_display_requires_degraded_label_when_stale():
    obs = _fresh(
        freshness_status=FreshnessStatus.STALE,
        degraded_label=None,
        freshness_age_seconds=200_000.0,
    )
    result = evaluate_eligibility(obs, now=NOW, consumer_kind="display")
    assert result.decision is EligibilityDecision.INELIGIBLE
    assert "DISPLAY_MISSING_DEGRADED_LABEL" in result.reasons

    obs2 = _fresh(
        freshness_status=FreshnessStatus.STALE,
        degraded_label="STALE research — do not use for proposals",
        freshness_age_seconds=200_000.0,
    )
    result2 = evaluate_eligibility(obs2, now=NOW, consumer_kind="display")
    assert result2.decision is EligibilityDecision.DISPLAY_ONLY
