from __future__ import annotations

import json
import pathlib

import pytest

from agent_runtime import read_http
import agent_runtime.maturity_observability as maturity_observability
from agent_runtime.maturity_observability import (
    API_CONTRACT,
    REVIEW_HEALTH,
    REVIEW_PROVENANCE,
    ReviewEvidence,
    _declared_sample_size,
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
    assert all(row["next_gate_state"] != "PASSED" for row in rows if row["review_health"] != "HEALTHY")


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


def test_frameworks_without_live_artifacts_preserve_unknown_sample_counts():
    rows = {row["agent_id"]: row for row in _rows()}
    for agent_id in ["hermes", "broker_cloud_oversight", "defense_adjudication", "concierge"]:
        row = rows[agent_id]
        assert row["sample_size"] is None
        assert row["required_sample_size"] is None
        assert row["sample_progress_state"] == "UNKNOWN"
        assert row["next_gate_state"] == "UNKNOWN"


def test_missing_agent_runtime_gate_source_does_not_fallback_to_100(monkeypatch):
    monkeypatch.setattr(maturity_observability, "_load_agent_runtime_min_artifact_gate", lambda: None)
    rows = {row["agent_id"]: row for row in build_observations(ROOT, observed_at="2026-07-30T13:00:00+00:00")}
    sentinel = rows["sentinel"]
    assert sentinel["required_sample_size"] is None
    assert sentinel["next_gate_state"] == "UNKNOWN"
    assert sentinel["sample_progress_state"] == "UNKNOWN"
    assert any("minimum artifact gate could not be verified" in item for item in sentinel["operator_checks_required"])


def test_explicit_source_sample_counts_preserve_zero_and_n():
    assert _declared_sample_size({"evidence": {"reviewed_artifacts": 0}}) == 0
    assert _declared_sample_size({"evidence": {"reviewed_artifacts": 7}}) == 7
    assert _declared_sample_size({"sample_size": 0}) == 0
    assert _declared_sample_size({"sample_size": 12}) == 12
    assert _declared_sample_size({}) is None


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


# ── WS-2: live runtime-evidence bridge (fail-closed by construction) ──────────

OBS = "2026-07-30T13:00:00+00:00"


class _FakeReader:
    """Read-only reader stub: list_runs + per-run list_artifacts/list_reviews/
    list_scores. Confers no mutation power. `raise_on` simulates a reader hiccup."""

    def __init__(self, runs, artifacts=None, reviews=None, scores=None, raise_on=None):
        self._runs = list(runs)
        self._artifacts = dict(artifacts or {})
        self._reviews = dict(reviews or {})
        self._scores = dict(scores or {})
        self._raise_on = raise_on

    def list_runs(self, *, limit, offset=0, agent_id=None, status=None):
        if self._raise_on == "list_runs":
            raise RuntimeError("reader boom")
        return self._runs[offset:offset + limit]

    def list_artifacts(self, run_id):
        return self._artifacts.get(run_id, [])

    def list_reviews(self, run_id):
        if self._raise_on == "list_reviews":
            raise RuntimeError("reader boom")
        return self._reviews.get(run_id, [])

    def list_scores(self, run_id):
        return self._scores.get(run_id, [])


def _find(rows, agent_id):
    return next(r for r in rows if r["agent_id"] == agent_id)


def _producer_reader(producer, *, verdict=None, created_at=OBS, n=120, reviewer="iris"):
    """A run where `producer` makes n artifacts, optionally each reviewed by
    `reviewer` with `verdict`. The board agent under test is the PRODUCER, whose
    own output IS the reviewed set → review_health reflects `verdict`."""
    arts = [{"artifact_id": f"a{i}", "producer_agent_id": producer} for i in range(n)]
    revs = ([{"artifact_id": f"a{i}", "reviewer_agent_id": reviewer,
              "verdict": verdict, "created_at": created_at} for i in range(n)]
            if verdict is not None else [])
    return _FakeReader([{"run_id": "r1", "agent_id": producer}],
                       artifacts={"r1": arts}, reviews={"r1": revs})


def _reviewer_reader(reviewer, *, producer="watch_producer_shadow", n=120):
    """A run where `producer` makes n artifacts and `reviewer` reviews them. The
    board agent under test is the REVIEWER — its OWN output is never reviewed, so
    review_health is NOT_RUN (fail-closed) even though it has real throughput.
    Mirrors the real LAB shape (watch_producer_shadow produced, sentinel_shadow
    reviewed)."""
    arts = [{"artifact_id": f"a{i}", "producer_agent_id": producer} for i in range(n)]
    revs = [{"artifact_id": f"a{i}", "reviewer_agent_id": reviewer,
             "verdict": "pass", "created_at": OBS} for i in range(n)]
    return _FakeReader([{"run_id": "r1", "agent_id": producer}],
                       artifacts={"r1": arts}, reviews={"r1": revs})


# MANDATED case 1: reader unavailable / empty → REPOSITORY_EVIDENCE, invents nothing

def test_bridge_reader_none_is_repository_evidence_zero_eligible():
    payload = maturity_payload(ROOT, observed_at=OBS, reader=None)
    rows = payload["data"]
    assert rows
    assert all(r["source_class"] == "REPOSITORY_EVIDENCE" for r in rows)
    assert payload["summary"]["eligible_for_human_review"] == 0
    assert payload["source_availability"]["agent_runtime_db"] == "UNVERIFIED"


def test_bridge_empty_reader_invents_no_rows_and_stays_repository_evidence():
    baseline = {r["agent_id"] for r in maturity_payload(ROOT, observed_at=OBS, reader=None)["data"]}
    payload = maturity_payload(ROOT, observed_at=OBS, reader=_FakeReader([]))
    assert {r["agent_id"] for r in payload["data"]} == baseline  # no fabricated agents
    assert all(r["source_class"] == "REPOSITORY_EVIDENCE" for r in payload["data"])
    assert payload["summary"]["eligible_for_human_review"] == 0
    assert payload["source_availability"]["agent_runtime_db"] == "CONNECTED_NO_RUNTIME_EVIDENCE"


def test_bridge_reader_error_fails_closed_to_repository_evidence():
    reader = _FakeReader([{"run_id": "r1", "agent_id": "sentinel"}], raise_on="list_runs")
    assert maturity_observability.collect_runtime_evidence(reader) == ({}, {})
    payload = maturity_payload(ROOT, observed_at=OBS, reader=reader)
    assert all(r["source_class"] == "REPOSITORY_EVIDENCE" for r in payload["data"])
    assert payload["summary"]["eligible_for_human_review"] == 0


# MANDATED case 2: degraded / stale / not-run / unknown live evidence never ELIGIBLE

@pytest.mark.parametrize("verdict, expect_health", [
    ("degraded", "DEGRADED_FALLBACK"),
    ("timeout", "TIMEOUT"),
    ("invalid", "INVALID_OUTPUT"),
    ("some_unmapped_verdict", "UNKNOWN"),
])
def test_bridge_nonhealthy_runtime_reviews_are_runtime_evidence_but_never_eligible(verdict, expect_health):
    reader = _producer_reader("sentinel", verdict=verdict)
    row = _find(maturity_payload(ROOT, observed_at=OBS, reader=reader)["data"], "sentinel")
    assert row["source_class"] == "RUNTIME_EVIDENCE"     # honest: live evidence exists
    assert row["sample_size"] == 120                      # real governed throughput
    assert row["review_health"] == expect_health
    assert row["promotion_eligibility"] != "ELIGIBLE_FOR_HUMAN_REVIEW"


def test_bridge_stale_healthy_review_is_stale_and_not_eligible(monkeypatch):
    monkeypatch.setenv("AGENT_FRESHNESS_DAYS", "1")
    reader = _producer_reader("sentinel", verdict="pass", created_at="2020-01-01T00:00:00+00:00")
    row = _find(maturity_payload(ROOT, observed_at=OBS, reader=reader)["data"], "sentinel")
    assert row["review_health"] == "STALE_CACHE"
    assert row["promotion_eligibility"] != "ELIGIBLE_FOR_HUMAN_REVIEW"


def test_bridge_reviewer_activity_is_runtime_evidence_but_notrun_and_not_eligible():
    # The real LAB shape: sentinel reviews another producer's artifacts; sentinel's
    # OWN output is never reviewed → NOT_RUN, never eligible, despite real throughput.
    reader = _reviewer_reader("sentinel", producer="watch_producer")
    row = _find(maturity_payload(ROOT, observed_at=OBS, reader=reader)["data"], "sentinel")
    assert row["source_class"] == "RUNTIME_EVIDENCE"
    assert row["sample_size"] == 120
    assert row["review_health"] == "NOT_RUN"
    assert row["promotion_eligibility"] == "NOT_ELIGIBLE"


def test_bridge_normalizes_shadow_suffix_to_board_id():
    # sentinel_shadow reviews watch_producer_shadow's artifacts → the board's
    # canonical `sentinel` row lights up; no `_shadow` / producer rows are invented.
    reader = _reviewer_reader("sentinel_shadow", producer="watch_producer_shadow")
    payload = maturity_payload(ROOT, observed_at=OBS, reader=reader)
    ids = {r["agent_id"] for r in payload["data"]}
    assert "sentinel_shadow" not in ids and "watch_producer_shadow" not in ids
    row = _find(payload["data"], "sentinel")
    assert row["source_class"] == "RUNTIME_EVIDENCE"
    assert row["sample_size"] == 120
    assert payload["source_availability"]["agent_runtime_db"] == "AVAILABLE"


# Healthy live evidence is labelled RUNTIME_EVIDENCE but still gated on framework gates
# (reader path never asserts gate completion — the honest current ceiling).

def test_bridge_healthy_runtime_reviews_are_runtime_evidence_but_gated(monkeypatch):
    monkeypatch.setenv("AGENT_FRESHNESS_DAYS", "100000")  # any date is fresh
    reader = _producer_reader("sentinel", verdict="pass", created_at="2026-07-01T00:00:00+00:00")
    row = _find(maturity_payload(ROOT, observed_at=OBS, reader=reader)["data"], "sentinel")
    assert row["source_class"] == "RUNTIME_EVIDENCE"
    assert row["freshness_state"] == "LIVE_RUNTIME_EVIDENCE"
    assert row["review_health"] == "HEALTHY"
    assert row["sample_size"] == 120
    assert row["promotion_eligibility"] == "HUMAN_REVIEW_REQUIRED"  # framework gates unmeasured
    assert maturity_payload(ROOT, observed_at=OBS, reader=reader)["summary"]["eligible_for_human_review"] == 0


# Proves the wiring WOULD populate ELIGIBLE once a measured-gates component (WS-3)
# supplies framework_gates_complete=True via the runtime overlay.

def test_bridge_would_populate_eligible_only_when_gates_measured():
    overlay = {"sentinel": {"source_class": "RUNTIME_EVIDENCE", "sample_size": 100,
                            "framework_gates_complete": True,
                            "effective_production_activation_verified": False}}
    reviews = {"sentinel": {"review_health": "HEALTHY", "status": "ok",
                            "review_provenance": "MODEL_REVIEW"}}
    row = _find(build_observations(ROOT, observed_at=OBS, review_records=reviews,
                                   runtime_evidence=overlay), "sentinel")
    assert row["source_class"] == "RUNTIME_EVIDENCE"
    assert row["promotion_eligibility"] == "ELIGIBLE_FOR_HUMAN_REVIEW"

    overlay["sentinel"]["framework_gates_complete"] = False  # partial gates → not eligible
    row2 = _find(build_observations(ROOT, observed_at=OBS, review_records=reviews,
                                    runtime_evidence=overlay), "sentinel")
    assert row2["promotion_eligibility"] != "ELIGIBLE_FOR_HUMAN_REVIEW"


def test_mvl_unknown_review_health_uses_actionable_hint_not_non_mvl():
    from agent_runtime.maturity_observability import _next_step_hint

    hint = _next_step_hint(
        lifecycle="SHADOW",
        environment="SHADOW",
        has_runtime_spec=True,
        source_class="RUNTIME_EVIDENCE",
        sample_size=130,
        required=100,
        review_health="UNKNOWN",
        eligibility="HUMAN_REVIEW_REQUIRED",
        framework_gates_complete=False,
        framework="agent-runtime-mvl",
    )
    assert "non-MVL" not in hint
    assert "Review health unknown" in hint

    gate_state, _, eligibility = _gate_state(130, 100, ReviewEvidence(review_health="UNKNOWN"))
    assert eligibility == "HUMAN_REVIEW_REQUIRED"
