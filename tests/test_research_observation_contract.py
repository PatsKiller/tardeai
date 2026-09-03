"""Contract tests for ResearchObservation provenance envelope."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.research_observation import (
    SCHEMA_VERSION,
    FreshnessStatus,
    QualityStatus,
    EntitlementStatus,
    FallbackState,
    make_research_observation,
    payload_source_hash,
    required_provenance_fields,
    wrap_research_record,
    wrap_no_data,
    wrap_gap,
    wrap_error,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "research_observation"

NOW = "2026-09-02T18:00:06+00:00"
T0 = "2026-09-02T18:00:00+00:00"
T1 = "2026-09-02T18:00:05+00:00"


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
        normalized_at=NOW,
        run_id="run-eligible-001",
        trace_id="trace:run-eligible-001",
        sequence_or_version="3",
        calculation_or_model_version="HermesResearchResult@v2",
        freshness_age_seconds=3600.0,
        durable_output_present=True,
        log_success_claimed=True,
        payload={"summary": "ok"},
        symbol_or_entity="AAPL",
        business_date="2026-09-02",
        session="RTH",
        fallback_state=FallbackState.NONE,
    )
    base.update(overrides)
    return make_research_observation(**base)


def test_schema_version_and_required_fields():
    assert SCHEMA_VERSION == "ResearchObservation@v1"
    req = required_provenance_fields()
    for key in (
        "source_identity",
        "provider",
        "provider_at",
        "observed_at",
        "received_at",
        "normalized_at",
        "freshness_status",
        "quality_status",
        "entitlement_status",
        "sequence_or_version",
        "source_hash",
        "calculation_or_model_version",
        "fallback_state",
        "trace_id",
        "run_id",
        "schema_version",
    ):
        assert key in req


def test_complete_eligible_record_has_no_missing_provenance():
    obs = _eligible()
    assert obs.is_complete_provenance()
    assert obs.freshness_status is FreshnessStatus.FRESH
    d = obs.to_dict()
    assert d["authority"] == "READ_ONLY_ADVISORY"
    assert d["source_hash"]
    assert len(d["source_hash"]) == 64


def test_source_hash_deterministic():
    a = payload_source_hash({"a": 1, "b": 2})
    b = payload_source_hash({"b": 2, "a": 1})
    assert a == b
    assert a != payload_source_hash({"a": 1, "b": 3})


def test_no_data_never_fresh():
    obs = wrap_no_data(
        source_identity="research_intelligence_feed",
        provider="ri_overnight",
        run_id="run-nodata",
        received_at=NOW,
        normalized_at=NOW,
    )
    assert obs.freshness_status is FreshnessStatus.NO_DATA
    assert obs.freshness_status is not FreshnessStatus.FRESH
    assert obs.durable_output_present is False


def test_gap_never_fresh():
    obs = wrap_gap(
        source_identity="research_intelligence_feed",
        provider="ri_freshness",
        run_id="run-gap",
        received_at=NOW,
        normalized_at=NOW,
        gap_reason="coverage_gaps:macro_geo",
    )
    assert obs.freshness_status is FreshnessStatus.GAP
    assert "GAP" in (obs.degraded_label or "")


def test_error_envelope():
    obs = wrap_error(
        source_identity="flash_llm_intelligence_runtime",
        provider="llm_enrichment",
        run_id="run-err",
        received_at=NOW,
        normalized_at=NOW,
        error="producer failed",
        log_success_claimed=True,
    )
    assert obs.freshness_status is FreshnessStatus.ERROR
    assert obs.quality_status is QualityStatus.FAILED


def test_wrap_fixture_eligible():
    raw = json.loads((FIXTURES / "eligible_complete.json").read_text())
    obs = wrap_research_record(
        raw,
        source_identity="hermes_research_results",
        provider="hermes_worker",
        freshness_status=FreshnessStatus.FRESH,
        entitlement_status=EntitlementStatus.INTERNAL,
        freshness_age_seconds=100.0,
    )
    assert obs.run_id == "run-eligible-001"
    assert obs.durable_output_present is True
    # secrets-like keys must not appear even if present
    assert "api_key" not in obs.payload_ref
    assert "raw_body" not in obs.payload_ref


def test_wrap_strips_secret_keys():
    obs = wrap_research_record(
        {
            "run_id": "r1",
            "trace_id": "t1",
            "provider_at": T0,
            "as_of": T0,
            "received_at": T1,
            "normalized_at": NOW,
            "quality_status": "OK",
            "entitlement_status": "INTERNAL",
            "sequence": "1",
            "model_version": "x",
            "api_key": "SECRET",
            "token": "SECRET",
            "summary": "ok",
        },
        source_identity="lesson_candidates",
        provider="build_lesson_candidates",
        freshness_status=FreshnessStatus.FRESH,
    )
    assert "api_key" not in obs.payload_ref
    assert "token" not in obs.payload_ref
    assert obs.payload_ref.get("summary") == "ok"


def test_missing_provenance_fixture():
    raw = json.loads((FIXTURES / "missing_provenance.json").read_text())
    obs = wrap_research_record(
        raw,
        source_identity="lesson_candidates",
        provider="unknown",
        run_id="",
        freshness_status=FreshnessStatus.PARTIAL,
    )
    missing = obs.missing_provenance_fields()
    assert "run_id" in missing or "trace_id" in missing
    assert "provider_at" in missing or "received_at" in missing
