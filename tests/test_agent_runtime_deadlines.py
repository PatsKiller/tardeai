from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.agent_runtime.contracts import AgentDefinition, BudgetPolicy, DeploymentState, Environment
from scripts.agent_runtime.journal import ShadowRunJournal
from scripts.agent_runtime.runtime import MvlRuntime


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="sentinel",
        display_name="Sentinel",
        role="Decision-integrity reflective critic",
        version="deadline-test-v1",
        owner="test-owner",
        allowed_job_types=("watch_ticket_review",),
        allowed_tools=("ticket.read",),
        retrieval_required=True,
        budget=BudgetPolicy(max_model_calls=1, max_tool_calls=1, max_cost_usd=0.0, deadline_seconds=5),
        deployment_state=DeploymentState.SHADOW,
        enabled=True,
    )


def build_runtime(
    tmp_path: Path,
    clock: MutableClock,
    *,
    retrieval_provider=None,
) -> MvlRuntime:
    return MvlRuntime(
        definition=definition(),
        journal=ShadowRunJournal(tmp_path / "shadow-runs", Environment.SHADOW),
        retrieval_provider=retrieval_provider or (lambda run_id, query: [{"ref": "fixture", "content": query}]),
        model_provider=lambda run_id, request: {"verdict": "PASS"},
        clock=clock,
    )


def start_run(subject: MvlRuntime):
    return subject.start(
        job_type="watch_ticket_review",
        objective="Deadline enforcement fixture.",
        input_payload={"symbol": "TEST"},
        validation_payload={"state": "PASS"},
    )


def test_deadline_expires_before_next_operation_and_records_terminal_failure(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc))
    subject = build_runtime(tmp_path, clock)
    run = start_run(subject)

    clock.advance(6)
    with pytest.raises(TimeoutError, match="deadline exceeded"):
        subject.retrieve(run.run_id, "fixture")

    state = subject.status(run.run_id)
    assert state["status"] == "FAILED"
    assert state["failure_code"] == "DEADLINE_EXCEEDED"
    assert state["deadline_seconds"] == 5
    assert state["elapsed_seconds"] == 6
    assert state["last_event_type"] == "RUN_FAILED"

    with pytest.raises(RuntimeError, match="failed run requires a new run envelope"):
        subject.resume(run.run_id)


def test_deadline_is_rechecked_after_provider_returns(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc))

    def slow_retrieval(run_id: str, query: str):
        clock.advance(6)
        return [{"ref": "late", "content": query}]

    subject = build_runtime(tmp_path, clock, retrieval_provider=slow_retrieval)
    run = start_run(subject)

    with pytest.raises(TimeoutError, match="deadline exceeded"):
        subject.retrieve(run.run_id, "fixture")

    state = subject.status(run.run_id)
    assert state["status"] == "FAILED"
    assert state["last_event_type"] == "RUN_FAILED"
    assert "retrieval_refs" not in state


def test_explicit_failure_is_terminal_and_explainable(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc))
    subject = build_runtime(tmp_path, clock)
    run = start_run(subject)

    subject.fail(run.run_id, "fixture provider unavailable", "PROVIDER_UNAVAILABLE")
    state = subject.status(run.run_id)
    assert state["status"] == "FAILED"
    assert state["failure_code"] == "PROVIDER_UNAVAILABLE"
    assert state["failure_reason"] == "fixture provider unavailable"

    with pytest.raises(RuntimeError, match="run is terminal: FAILED"):
        subject.retrieve(run.run_id, "fixture")
