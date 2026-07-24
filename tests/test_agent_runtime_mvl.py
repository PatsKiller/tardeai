from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_runtime.contracts import (
    AgentDefinition,
    BudgetPolicy,
    DeploymentState,
    Environment,
    ReviewVerdict,
    ToolDecision,
    ToolPolicy,
    ToolRequest,
    canonical_hash,
)
from scripts.agent_runtime.hermes import HermesHypothesisGateway
from scripts.agent_runtime.journal import ShadowRunJournal
from scripts.agent_runtime.operator import OpenClawOperatorGateway
from scripts.agent_runtime.registry import load_registry
from scripts.agent_runtime.runtime import MvlRuntime


ROOT = Path(__file__).resolve().parents[1]


def sentinel_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="sentinel",
        display_name="Sentinel",
        role="Decision-integrity reflective critic",
        version="test-v1",
        owner="test-owner",
        allowed_job_types=("watch_ticket_review",),
        allowed_tools=("kb.search", "ticket.read", "artifact.write"),
        denied_tools=("score.write",),
        retrieval_required=True,
        budget=BudgetPolicy(max_model_calls=2, max_tool_calls=3, max_cost_usd=0.0, deadline_seconds=60),
        deployment_state=DeploymentState.SHADOW,
        enabled=True,
    )


def runtime(tmp_path: Path) -> MvlRuntime:
    journal = ShadowRunJournal(tmp_path / "shadow-runs", Environment.SHADOW)
    return MvlRuntime(
        definition=sentinel_definition(),
        journal=journal,
        retrieval_provider=lambda run_id, query: [
            {"ref": "lesson:stop-direction", "content": "A long stop must remain below entry."},
            {"ref": "case:known-bad-001", "content": "Blocked cards may not expose current mechanics."},
        ],
        model_provider=lambda run_id, request: {
            "verdict": "CAUTION",
            "contradictions": ["ticket needs independent arithmetic check"],
            "request_hash": canonical_hash(request),
        },
    )


def start_run(subject: MvlRuntime):
    return subject.start(
        job_type="watch_ticket_review",
        objective="Challenge one deterministic Watch ticket without changing it.",
        input_payload={"symbol": "TEST", "ticket": {"entry": 10.0, "stop": 9.5}},
        validation_payload={"state": "PASS", "hash": "fixture-validation"},
    )


def test_registry_matches_canonical_shadow_contract() -> None:
    registry = load_registry(ROOT / "config" / "agent_runtime_mvl.json")
    assert {"sentinel", "darwin", "reflection", "iris", "hermes", "concierge"} <= set(registry)
    assert registry["sentinel"].deployment_state is DeploymentState.SHADOW
    assert registry["sentinel"].retrieval_required is True
    assert registry["hermes"].enabled is False
    assert "hypothesis.promote" in registry["hermes"].denied_tools


def test_forbidden_authorities_are_denied_even_if_requested() -> None:
    definition = sentinel_definition()
    for tool in [
        "broker.submit",
        "order.place",
        "trade.execute",
        "2fa.unlock",
        "secrets.read",
        "prod_db.write",
        "config.promote",
        "shell.exec",
        "systemd.restart",
    ]:
        decision = ToolPolicy.evaluate(
            definition,
            ToolRequest(run_id="run_fixture", tool_name=tool, arguments={}, environment=Environment.SHADOW),
        )
        assert decision.decision is ToolDecision.DENY


def test_explicit_read_tool_is_allowed_and_audited(tmp_path: Path) -> None:
    subject = runtime(tmp_path)
    run = start_run(subject)
    result = subject.invoke_tool(run.run_id, "ticket.read", {"symbol": "TEST"}, lambda args: {"ticket": args["symbol"]})
    assert result == {"ticket": "TEST"}
    state = subject.status(run.run_id)
    assert state["tool_calls"] == 1
    assert state["last_event_type"] == "TOOL_COMPLETED"


def test_retrieval_is_required_before_reasoning(tmp_path: Path) -> None:
    subject = runtime(tmp_path)
    run = start_run(subject)
    with pytest.raises(RuntimeError, match="retrieval-before-reasoning"):
        subject.reason(
            run.run_id,
            prompt_version="sentinel-test-v1",
            provider_family="local",
            model="fixture-model",
            request_payload={"ticket": "fixture"},
        )


def test_full_run_checkpoints_review_and_score_are_independent(tmp_path: Path) -> None:
    subject = runtime(tmp_path)
    run = start_run(subject)
    retrieval = subject.retrieve(run.run_id, "known contradictions for TEST")
    assert len(retrieval) == 2
    output = subject.reason(
        run.run_id,
        prompt_version="sentinel-test-v1",
        provider_family="local",
        model="fixture-model",
        request_payload={"ticket": "fixture", "retrieval_refs": [row["ref"] for row in retrieval]},
    )
    artifact = subject.create_artifact(
        run.run_id,
        artifact_type="watch_ticket_critique",
        payload=output,
        prompt_version="sentinel-test-v1",
        provider_family="local",
        model="fixture-model",
    )
    review = subject.record_review(run.run_id, artifact, "iris", ReviewVerdict.CAUTION, ["Evidence is present; arithmetic remains deterministic."])
    score = subject.record_score(run.run_id, artifact, "darwin", {"grounding": 1.0, "utility": 0.5})
    assert review.reviewer_agent_id == "iris"
    assert score.scorer_agent_id == "darwin"
    subject.complete(run.run_id)
    state = subject.status(run.run_id)
    assert state["status"] == "COMPLETED"
    assert state["retrieval_count"] == 2
    assert state["model_calls"] == 1
    assert state["artifact"]["retrieval_refs"] == ["lesson:stop-direction", "case:known-bad-001"]


def test_agent_cannot_review_or_score_its_own_artifact(tmp_path: Path) -> None:
    subject = runtime(tmp_path)
    run = start_run(subject)
    subject.retrieve(run.run_id, "fixture")
    output = subject.reason(
        run.run_id,
        prompt_version="v1",
        provider_family="local",
        model="fixture",
        request_payload={"fixture": True},
    )
    artifact = subject.create_artifact(
        run.run_id,
        artifact_type="critique",
        payload=output,
        prompt_version="v1",
        provider_family="local",
        model="fixture",
    )
    with pytest.raises(ValueError, match="may not review its own"):
        subject.record_review(run.run_id, artifact, "sentinel", ReviewVerdict.PASS, [])
    with pytest.raises(ValueError, match="may not score its own"):
        subject.record_score(run.run_id, artifact, "sentinel", {"utility": 1.0})


def test_cancel_and_resume_are_governed_openclaw_commands(tmp_path: Path) -> None:
    subject = runtime(tmp_path)
    run = start_run(subject)
    gateway = OpenClawOperatorGateway(subject)
    explanation = gateway.execute(gateway.parse(f"explain {run.run_id}"))
    assert explanation["authority"].startswith("reflective artifacts only")
    gateway.execute(gateway.parse(f"cancel {run.run_id} operator stop"))
    assert subject.status(run.run_id)["status"] == "CANCELLED"
    with pytest.raises(RuntimeError, match="cancelled run"):
        gateway.execute(gateway.parse(f"resume {run.run_id}"))
    with pytest.raises(PermissionError):
        gateway.parse(f"shell {run.run_id}")


def test_journal_detects_tampering(tmp_path: Path) -> None:
    subject = runtime(tmp_path)
    run = start_run(subject)
    path = tmp_path / "shadow-runs" / f"{run.run_id}.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[0])
    payload["payload"]["status"] = "COMPLETED"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash-chain failure"):
        subject.status(run.run_id)


def test_production_looking_journal_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="production-looking"):
        ShadowRunJournal(tmp_path / "trade-ai-prod" / "runs", Environment.SHADOW)


def test_secret_like_payload_is_refused(tmp_path: Path) -> None:
    subject = runtime(tmp_path)
    with pytest.raises(ValueError, match="secret-like field"):
        subject.start(
            job_type="watch_ticket_review",
            objective="fixture",
            input_payload={"api_key": "must-not-enter-agent-context"},
            validation_payload={"state": "PASS"},
        )


def test_hermes_can_preregister_but_cannot_promote(tmp_path: Path) -> None:
    subject = runtime(tmp_path)
    run = start_run(subject)
    gateway = HermesHypothesisGateway(subject.journal)
    hypothesis = gateway.preregister(
        run_id=run.run_id,
        title="Fixture threshold hypothesis",
        claim="A frozen threshold may reduce false positives in shadow evaluation.",
        frozen_inputs={"threshold": 0.7, "source_hash": "fixture"},
        evaluation_plan={"mode": "walk_forward", "sessions": 20},
        success_metrics=["false_positive_rate decreases"],
        failure_metrics=["missed_detection_rate increases"],
        rollback_plan="Discard the candidate; production remains unchanged.",
    )
    assert hypothesis.status == "PREREGISTERED_SHADOW"
    with pytest.raises(PermissionError, match="cannot promote"):
        gateway.promote(hypothesis)
