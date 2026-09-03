"""Downstream consumers reject ineligible records and accept complete eligible ones."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.research_observation import (
    EligibilityDecision,
    EntitlementStatus,
    FallbackState,
    FreshnessStatus,
    QualityStatus,
    assert_eligible_or_raise,
    gate_for_consumer,
    make_research_observation,
)
from scripts.lib.research_observation.consumer_gate import IneligibleResearchError

NOW = datetime(2026, 9, 2, 18, 30, 0, tzinfo=timezone.utc)
T0 = "2026-09-02T18:00:00+00:00"
T1 = "2026-09-02T18:00:05+00:00"
T2 = "2026-09-02T18:00:06+00:00"


def _eligible(**overrides):
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


def test_proposal_consumer_accepts_eligible():
    obs = _eligible()
    gate = gate_for_consumer(
        obs,
        consumer_id="cio_wake_research_gate",
        consumer_kind="proposal",
        now=NOW,
        expected_run_id="run-ok",
        expected_source_hash=obs.source_hash,
    )
    assert gate.accepted
    assert gate.decision is EligibilityDecision.ELIGIBLE


def test_agent_consumer_rejects_stale():
    obs = _eligible(freshness_status=FreshnessStatus.STALE, freshness_age_seconds=200_000.0)
    gate = gate_for_consumer(
        obs,
        consumer_id="proposal_surfaces",
        consumer_kind="agent",
        now=NOW,
    )
    assert not gate.accepted
    assert gate.decision is EligibilityDecision.INELIGIBLE


def test_agent_rejects_unknown_entitlement():
    obs = _eligible(entitlement_status=EntitlementStatus.UNKNOWN)
    gate = gate_for_consumer(obs, consumer_id="proposal_surfaces", consumer_kind="agent", now=NOW)
    assert not gate.accepted


def test_display_accepts_stale_with_label():
    obs = _eligible(
        freshness_status=FreshnessStatus.STALE,
        freshness_age_seconds=200_000.0,
        degraded_label="STALE — display only",
    )
    gate = gate_for_consumer(
        obs,
        consumer_id="/v3/research-intelligence",
        consumer_kind="display",
        now=NOW,
    )
    assert gate.accepted
    assert gate.decision is EligibilityDecision.DISPLAY_ONLY


def test_display_rejects_stale_without_label():
    obs = _eligible(
        freshness_status=FreshnessStatus.STALE,
        freshness_age_seconds=200_000.0,
        degraded_label=None,
    )
    gate = gate_for_consumer(
        obs,
        consumer_id="/v3/hermes",
        consumer_kind="display",
        now=NOW,
    )
    assert not gate.accepted


def test_assert_eligible_raises():
    obs = _eligible(quality_status=QualityStatus.FAILED)
    with pytest.raises(IneligibleResearchError) as ei:
        assert_eligible_or_raise(
            obs,
            consumer_id="cio_wake_research_gate",
            consumer_kind="proposal",
            now=NOW,
        )
    assert "INELIGIBLE" in str(ei.value)


def test_assert_eligible_passes():
    obs = _eligible()
    gate = assert_eligible_or_raise(
        obs,
        consumer_id="cio_wake_research_gate",
        consumer_kind="proposal",
        now=NOW,
        expected_run_id="run-ok",
    )
    assert gate.accepted


def test_partial_and_error_rejected_by_proposal():
    for status in (FreshnessStatus.PARTIAL, FreshnessStatus.ERROR, FreshnessStatus.INELIGIBLE):
        obs = _eligible(freshness_status=status)
        gate = gate_for_consumer(obs, consumer_id="proposal_surfaces", consumer_kind="proposal", now=NOW)
        assert not gate.accepted, status
