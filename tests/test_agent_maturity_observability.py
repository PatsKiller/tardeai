from __future__ import annotations

import json
import pathlib

import pytest

from agent_runtime import read_http
from agent_runtime.maturity_observability import (
    API_CONTRACT,
    REVIEW_HEALTH,
    REVIEW_PROVENANCE,
    ReviewEvidence,
    _gate_state,
    analyze_outcome_completeness,
    build_observations,
    maturity_payload,
    sanitize_runtime_inventory,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rows():
    return build_observations(ROOT, observed_at="2026-07-30T13:00:00+00:00")


def test_all_observations_map_to_canonical_schema_and_human_only_authority():
    rows = _rows()
    assert rows
    required_fields = {
        "schema_version",
        "observed_at",
        "agent_id",
        "subsystem",
        "declared_lifecycle_state",
        "effective_authority_state",
        "maturity_framework",
        "sample_size",
        "required_sample_size",
        "next_gate_state",
        "promotion_eligibility",
        "promotion_authority",
        "automatic_promotion_permitted",
        "review_provenance",
        "review_health",
        "source_class",
        "evidence_refs",
        "warnings",
        "operator_checks_required",
    }
    for row in rows:
        assert required_fields.issubset(row)
        assert row["promotion_authority"] == "HUMAN_ONLY"
        assert row["automatic_promotion_permitted"] is False
        assert row["production_activation_authorized"] in {False, None}
        assert row["declared_production_activation_authorized"] in {False, None}
        assert row["effective_production_activation_verified"] is False
        assert "NO FINANCIAL AUTHORITY" in row["denied_authorities"]


def test_unknown_and_not_run_data_remain_visible_not_passed():
    rows = _rows()
    not_run = [row for row in rows if row["review_health"] == "NOT_RUN"]
    assert not_run
    assert all(row["next_gate_state"] != "PASSED" for row in not_run)
    assert all(row["promotion_eligibility"] != "ELIGIBLE_FOR_HUMAN_REVIEW" for row in not_run)
    assert any(row["sample_progress_state"] == "CAPPED_BY_SAMPLE_SIZE" for row in rows)


def test_unrelated_maturity_frameworks_are_not_averaged():
    payload = maturity_payload(ROOT, observed_at="2026-07-30T13:00:00+00:00")
    frameworks = payload["summary"]["frameworks"]
    assert "agent-runtime-mvl" in frameworks
    assert "hermes" in frameworks
    assert "composite_score" not in payload["summary"]
    hermes = next(row for row in payload["data"] if row["agent_id"] == "hermes")
    assert hermes["maturity_framework_version"] == "maturity-v2"
    assert hermes["maturity_score"] is None
    assert hermes["required_sample_size"] is None
    assert hermes["next_gate_state"] == "UNKNOWN"
    assert any("Exact Hermes" in item for item in hermes["operator_checks_required"])


def test_activation_authorization_is_declared_separate_from_live_verification():
    rows = {row["agent_id"]: row for row in _rows()}
    assert rows["sentinel"]["declared_production_activation_authorized"] is False
    assert rows["sentinel"]["effective_production_activation_verified"] is False
    assert rows["sentinel"]["activation_evidence_state"] == "REPOSITORY_EVIDENCE"
    assert rows["broker_cloud_oversight"]["declared_production_activation_authorized"] is None
    assert rows["broker_cloud_oversight"]["activation_evidence_state"] == "UNVERIFIED"


@pytest.mark.parametrize("state", sorted(REVIEW_PROVENANCE))
def test_review_provenance_enum_is_supported(state):
    assert state in REVIEW_PROVENANCE


@pytest.mark.parametrize("state", sorted(REVIEW_HEALTH))
def test_review_health_enum_is_supported(state):
    assert state in REVIEW_HEALTH


def test_review_provenance_distinguishes_fallback_cache_timeout_missing_invalid_and_incomplete():
    records = {
        "sentinel": {"review_provenance": "local_llm", "review_health": "HEALTHY", "model": "synthetic-model", "reviewed_at": "2026-07-30T12:00:00Z"},
        "darwin": {"review_provenance": "deterministic_fallback", "reviewed_at": "2026-07-30T12:01:00Z"},
        "iris": {"cached": True, "stale": True, "reviewed_at": "2026-07-30T12:02:00Z"},
        "reflection": {"status": "timeout", "reviewed_at": "2026-07-30T12:03:00Z"},
        "maria": {"status": "missing", "reviewed_at": "2026-07-30T12:04:00Z"},
        "risk_agent": {"status": "incomplete", "reviewed_at": "2026-07-30T12:05:00Z"},
        "steph": {"status": "invalid", "reviewed_at": "2026-07-30T12:06:00Z"},
    }
    by_id = {row["agent_id"]: row for row in build_observations(ROOT, observed_at="2026-07-30T13:00:00+00:00", review_records=records)}
    assert by_id["sentinel"]["review_provenance"] == "MODEL_REVIEW"
    assert by_id["sentinel"]["review_health"] == "HEALTHY"
    assert by_id["darwin"]["review_provenance"] == "DETERMINISTIC_FALLBACK"
    assert by_id["darwin"]["review_health"] == "DEGRADED_FALLBACK"
    assert by_id["iris"]["review_provenance"] == "CACHED_MODEL_REVIEW"
    assert by_id["iris"]["review_health"] == "STALE_CACHE"
    assert by_id["reflection"]["review_health"] == "TIMEOUT"
    assert by_id["maria"]["review_health"] == "MISSING_REVIEWER"
    assert by_id["risk_agent"]["review_health"] == "INCOMPLETE_CONSENSUS"
    assert by_id["steph"]["review_health"] == "INVALID_OUTPUT"


@pytest.mark.parametrize(
    ("health", "expected_state", "expected_eligibility"),
    [
        ("NOT_RUN", "NOT_RUN", "NOT_ELIGIBLE"),
        ("UNKNOWN", "UNKNOWN", "UNKNOWN"),
        ("DEGRADED_FALLBACK", "INSUFFICIENT_EVIDENCE", "HUMAN_REVIEW_REQUIRED"),
        ("STALE_CACHE", "STALE", "HUMAN_REVIEW_REQUIRED"),
        ("TIMEOUT", "FAILED", "NOT_ELIGIBLE"),
        ("MISSING_REVIEWER", "INSUFFICIENT_EVIDENCE", "HUMAN_REVIEW_REQUIRED"),
        ("INCOMPLETE_CONSENSUS", "INSUFFICIENT_EVIDENCE", "HUMAN_REVIEW_REQUIRED"),
        ("PROVIDER_UNAVAILABLE", "INSUFFICIENT_EVIDENCE", "HUMAN_REVIEW_REQUIRED"),
        ("INVALID_OUTPUT", "FAILED", "NOT_ELIGIBLE"),
    ],
)
def test_degraded_review_states_with_sufficient_samples_cannot_pass(health, expected_state, expected_eligibility):
    state, reason, eligibility = _gate_state(
        100, 100, ReviewEvidence(review_health=health), framework_gates_complete=True
    )
    assert state == expected_state
    assert state != "PASSED"
    assert eligibility == expected_eligibility
    assert eligibility != "ELIGIBLE_FOR_HUMAN_REVIEW"
    assert reason


def test_healthy_review_with_sufficient_samples_requires_remaining_framework_gates():
    incomplete_state, incomplete_reason, incomplete_eligibility = _gate_state(
        100, 100, ReviewEvidence(review_health="HEALTHY"), framework_gates_complete=False
    )
    assert incomplete_state == "INSUFFICIENT_EVIDENCE"
    assert incomplete_eligibility == "HUMAN_REVIEW_REQUIRED"
    assert "remaining framework gates" in incomplete_reason

    state, reason, eligibility = _gate_state(
        100, 100, ReviewEvidence(review_health="HEALTHY"), framework_gates_complete=True
    )
    assert state == "PASSED"
    assert reason is None
    assert eligibility == "ELIGIBLE_FOR_HUMAN_REVIEW"


def test_agent_maturity_api_is_get_only_and_zero_authority_without_runtime_reader():
    status, body = read_http.dispatch(None, "GET", "/api/v3/agent-maturity", {})
    assert status == 200
    assert body["contract"] == API_CONTRACT
    assert body["read_only"] is True
    assert all(v is False for v in body["authority"].values())
    assert body["source_availability"]["production_runtime"] == "UNVERIFIED"

    status, body = read_http.dispatch(None, "POST", "/api/v3/agent-maturity", {})
    assert status == 405
    assert body["read_only"] is True
    assert body["data"] is None
    assert all(v is False for v in body["authority"].values())


def test_agent_maturity_detail_and_summary_routes():
    status, body = read_http.dispatch(None, "GET", "/api/v3/agent-maturity/summary", {})
    assert status == 200
    assert "data" not in body
    assert body["summary"]["total_agents"] > 0

    status, body = read_http.dispatch(None, "GET", "/api/v3/agent-maturity/sentinel", {})
    assert status == 200
    assert body["data"]["agent_id"] == "sentinel"


def test_dry_run_preserves_source_ids_and_never_writes():
    report = analyze_outcome_completeness([
        {
            "source_id": "artifact-1",
            "outcome": "hit",
            "decision_timestamp": "2026-07-01T00:00:00Z",
            "outcome_timestamp": "2026-07-02T00:00:00Z",
            "agent_id": "sentinel",
            "model": "synthetic",
            "prompt_version": "p1",
            "input_hash": "h1",
        },
        {"source_id": "artifact-1", "outcome": "miss"},
        {"outcome": None},
    ])
    assert report["dry_run"] is True
    assert report["write_attempted"] is False
    assert report["estimated_sample_size_impact"] == 2
    assert report["conflicts_or_duplicates"] == [{"source_id": "artifact-1", "reason": "conflicting outcome"}]
    assert report["candidate_derived_records"][0]["source_ids"] == ["artifact-1"]
    assert report["candidate_derived_records"][0]["write_attempted"] is False


def test_sanitized_runtime_inventory_excludes_secret_fields():
    clean = sanitize_runtime_inventory({
        "schema_version": "openclaw-runtime-inventory-v1",
        "installed_version": "1.2.3",
        "service_unit_name": "openclaw.service",
        "declared_agent_ids": ["concierge"],
        "enabled": False,
        "verification_status": "UNVERIFIED",
    })
    assert clean["installed_version"] == "1.2.3"
    assert "token" not in json.dumps(clean).lower()
    with pytest.raises(ValueError):
        sanitize_runtime_inventory({"api_token": "synthetic-secret"})


def test_frontend_scoreboard_contains_truth_labels_and_no_authority_controls():
    page = (ROOT / "apps/command-center-v3/src/pages/AgentRuntimeHub.tsx").read_text(encoding="utf-8")
    adapter = (ROOT / "apps/command-center-v3/src/lib/agentMaturityObservability.ts").read_text(encoding="utf-8")
    for label in [
        "HUMAN REVIEW REQUIRED",
        "ELIGIBLE FOR HUMAN REVIEW",
        "NOT RUN",
        "CAPPED BY SAMPLE SIZE",
        "DEGRADED — DETERMINISTIC FALLBACK",
        "STALE CACHED REVIEW",
        "RUNTIME STATUS UNVERIFIED",
        "NO FINANCIAL AUTHORITY",
    ]:
        assert label in page
    assert "automatic_promotion_permitted !== false" in adapter
    assert "promotion_authority !== 'HUMAN_ONLY'" in adapter
    assert "type=\"button\">Promote" not in page
    assert "type=\"button\">Activate" not in page
    assert "type=\"button\">Deploy" not in page
