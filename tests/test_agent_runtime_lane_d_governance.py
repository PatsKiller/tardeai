from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.agent_runtime.agents.base import OutputKind
from scripts.agent_runtime.agents.definitions import FLEET, spec
from scripts.agent_runtime.agents.dispatcher import (
    BoundedDispatcher,
    CircuitBreaker,
    JobOutcome,
    JobRequest,
    batch_summary,
)
from scripts.agent_runtime.agents.governed_output import (
    GovernedOutputError,
    emit_governed_output,
)
from scripts.agent_runtime.agents.maturity_gates import (
    GATE_IDS,
    GateStatus,
    assert_not_operational,
    evaluate_gates,
)
from scripts.agent_runtime.agents.read_projection import (
    agent_promotion_readmodel,
    fleet_promotion_readmodel,
)


# ---- governed output --------------------------------------------------------

def test_governed_output_is_advisory_and_draft_only() -> None:
    out = emit_governed_output(
        spec("darwin"), OutputKind.SCORECARD, {"artifact": "a", "dimensions": {"accuracy": 0.5}}
    )
    assert out.authority == "ADVISORY_ONLY"
    assert out.target == "DRAFT_ONLY"
    assert out.as_dict()["output_hash"]


def test_governed_output_rejects_disallowed_kind() -> None:
    with pytest.raises(GovernedOutputError):
        emit_governed_output(spec("darwin"), OutputKind.CANDIDATE_HYPOTHESIS, {"x": 1})


def test_governed_output_rejects_forbidden_action_field() -> None:
    with pytest.raises(GovernedOutputError):
        emit_governed_output(spec("aegis"), OutputKind.REMEDIATION_PROPOSAL, {"deploy": True})


def test_governed_output_rejects_forbidden_action_verb_in_value() -> None:
    with pytest.raises(GovernedOutputError):
        emit_governed_output(
            spec("aegis"), OutputKind.REMEDIATION_PROPOSAL, {"action": "please merge the branch"}
        )


def test_governed_output_rejects_secret_material() -> None:
    with pytest.raises(GovernedOutputError):
        emit_governed_output(spec("sentinel"), OutputKind.INTEGRITY_REVIEW, {"api_key": "x"})


def test_draft_pr_output_without_execution_verbs_is_allowed() -> None:
    out = emit_governed_output(
        spec("aegis"),
        OutputKind.DRAFT_PR,
        {"title": "Investigate retry gap", "body": "Add a bounded retry test.", "branch_hint": "codex/retry"},
    )
    assert out.kind == "DRAFT_PR"


# ---- maturity gates ---------------------------------------------------------

def test_gates_default_to_not_yet_measured_and_not_promotable() -> None:
    report = evaluate_gates(spec("sentinel"))
    assert len(report.gates) == len(GATE_IDS)
    assert all(g.status is GateStatus.NOT_YET_MEASURED for g in report.gates)
    assert report.promotable is False
    assert len(report.blockers) == len(GATE_IDS)


def test_partial_measurement_still_blocks_promotion() -> None:
    measurements = {gid: (1.0 if gid != "authority_violations" else 0) for gid in GATE_IDS}
    # leave one gate unmeasured
    measurements.pop("operator_usefulness")
    measurements["min_artifact_population"] = 100
    measurements["rollback_test_passed"] = True
    report = evaluate_gates(spec("darwin"), measurements)
    assert report.promotable is False
    assert any("operator_usefulness" in b for b in report.blockers)


def test_all_gates_measured_and_passing_is_promotable() -> None:
    measurements = {
        "min_artifact_population": 150,
        "retrieval_provenance_completeness": 1.0,
        "independent_review_coverage": 1.0,
        "independent_score_coverage": 1.0,
        "contradiction_rate": 0.0,
        "unsupported_claim_rate": 0.0,
        "stale_input_refusal_accuracy": 1.0,
        "deadline_budget_adherence": 1.0,
        "duplicate_run_rate": 0.0,
        "operator_usefulness": 0.9,
        "rollback_test_passed": True,
        "authority_violations": 0,
    }
    report = evaluate_gates(spec("sentinel"), measurements)
    assert report.promotable is True
    assert report.blockers == ()


def test_failing_threshold_reports_fail() -> None:
    measurements = {"authority_violations": 1}
    report = evaluate_gates(spec("iris"), measurements)
    failed = [g for g in report.gates if g.gate_id == "authority_violations"][0]
    assert failed.status is GateStatus.FAIL


def test_assert_not_operational_raises_when_state_operational_but_gates_unmet() -> None:
    import dataclasses

    from scripts.agent_runtime.contracts import DeploymentState

    s = spec("sentinel")
    # Only assert_not_operational is exercised; validate() would independently reject this.
    escalated = dataclasses.replace(
        s, definition=dataclasses.replace(s.definition, deployment_state=DeploymentState.OPERATIONAL)
    )
    report = evaluate_gates(s)  # not promotable
    with pytest.raises(PermissionError):
        assert_not_operational(escalated, report)


# ---- dispatcher -------------------------------------------------------------

def _job(agent_id: str, ih: str, enqueued: datetime, dedup: str | None = None) -> JobRequest:
    return JobRequest(
        agent_id=agent_id,
        job_type="watch_ticket_review",
        input_hash=ih,
        enqueued_at=enqueued.isoformat(),
        dedup_value=dedup or ih,
    )


def test_dispatcher_processes_fresh_jobs_and_dedups() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    seen: list[str] = []
    d = BoundedDispatcher(
        spec("darwin"),
        processor=lambda job: seen.append(job.input_hash) or {},
        max_concurrency=10,
        clock=lambda: now,
    )
    jobs = [_job("darwin", "a", now, "k1"), _job("darwin", "b", now, "k1"), _job("darwin", "c", now, "k2")]
    results = d.process_batch(jobs)
    outcomes = [r.outcome for r in results]
    assert outcomes[0] is JobOutcome.COMPLETED
    assert outcomes[1] is JobOutcome.REFUSED_DUPLICATE
    assert outcomes[2] is JobOutcome.COMPLETED
    assert seen == ["a", "c"]


def test_dispatcher_refuses_stale_input() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    stale = now - timedelta(seconds=spec("sentinel").stale_input_seconds + 5)
    d = BoundedDispatcher(spec("sentinel"), processor=lambda job: {}, clock=lambda: now)
    results = d.process_batch([_job("sentinel", "old", stale)])
    assert results[0].outcome is JobOutcome.REFUSED_STALE


def test_dispatcher_refuses_disabled_second_wave_agent() -> None:
    from dataclasses import replace

    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    maria = spec("maria")
    disabled = replace(maria, definition=replace(maria.definition, enabled=False))
    d = BoundedDispatcher(disabled, processor=lambda job: {}, clock=lambda: now)
    results = d.process_batch([_job("maria", "x", now)])
    assert results[0].outcome is JobOutcome.REFUSED_DISABLED


def test_dispatcher_refuses_wrong_agent_job() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    d = BoundedDispatcher(spec("sentinel"), processor=lambda job: {}, clock=lambda: now)
    results = d.process_batch([_job("darwin", "x", now)])
    assert results[0].outcome is JobOutcome.REFUSED_WRONG_AGENT


def test_circuit_breaker_opens_after_threshold_and_blocks_further_jobs() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)

    def boom(job: JobRequest):
        raise RuntimeError("processor failure")

    breaker = CircuitBreaker(threshold=spec("sentinel").circuit_breaker_trips_open_after)
    d = BoundedDispatcher(spec("sentinel"), processor=boom, max_concurrency=10, clock=lambda: now, breaker=breaker)
    jobs = [_job("sentinel", f"j{i}", now, f"k{i}") for i in range(5)]
    results = d.process_batch(jobs)
    failed = sum(1 for r in results if r.outcome is JobOutcome.FAILED)
    opened = sum(1 for r in results if r.outcome is JobOutcome.CIRCUIT_OPEN)
    assert failed == spec("sentinel").circuit_breaker_trips_open_after
    assert opened == 5 - failed
    assert breaker.is_open is True


def test_dispatcher_honors_cancellation() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    d = BoundedDispatcher(
        spec("sentinel"), processor=lambda job: {}, clock=lambda: now, should_cancel=lambda: True
    )
    results = d.process_batch([_job("sentinel", "x", now)])
    assert results[0].outcome is JobOutcome.CANCELLED


def test_batch_summary_counts_outcomes() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    d = BoundedDispatcher(spec("darwin"), processor=lambda job: {}, max_concurrency=10, clock=lambda: now)
    results = d.process_batch([_job("darwin", "a", now, "k1"), _job("darwin", "b", now, "k1")])
    summary = batch_summary(results)
    assert summary["total"] == 2
    assert summary["outcomes"]["COMPLETED"] == 1
    assert summary["outcomes"]["REFUSED_DUPLICATE"] == 1


# ---- read projection --------------------------------------------------------

def test_promotion_readmodel_without_evidence_is_not_run_and_not_promotable() -> None:
    model = agent_promotion_readmodel(spec("sentinel"))
    assert model["data_state"] == "NOT_RUN"
    assert model["evidence_source"] == "NONE"
    assert model["promotable"] is False
    assert model["run_evidence"] is None
    assert len(model["promotion_blockers"]) == len(GATE_IDS)


def test_promotion_readmodel_with_evidence_is_marked_live() -> None:
    model = agent_promotion_readmodel(
        spec("sentinel"), run_evidence={"last_run": "run_1", "status": "COMPLETED"}
    )
    assert model["data_state"] == "LIVE"
    assert model["evidence_source"] == "AUTHORITATIVE"


def test_fleet_readmodel_lists_all_agents_and_denies_activation() -> None:
    model = fleet_promotion_readmodel()
    assert model["production_activation_authorized"] is False
    assert len(model["agents"]) == len(FLEET)
    assert all(a["data_state"] == "NOT_RUN" for a in model["agents"])
