from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Callable, Mapping, Sequence

from .contracts import (
    AgentDefinition,
    Artifact,
    Environment,
    Review,
    ReviewVerdict,
    RunEnvelope,
    RunStatus,
    Score,
    ToolDecision,
    ToolPolicy,
    ToolRequest,
    assert_no_secret_material,
    canonical_hash,
    utc_now,
)
from .journal import ShadowRunJournal

RetrievalProvider = Callable[[str, str], Sequence[Mapping[str, Any]]]
ModelProvider = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class MvlRuntime:
    """Durable shadow implementation of the first agentic loop.

    It intentionally does not expose arbitrary shell, production database,
    broker, order, approval, 2FA, credential, or config-promotion methods.
    """

    def __init__(
        self,
        definition: AgentDefinition,
        journal: ShadowRunJournal,
        retrieval_provider: RetrievalProvider,
        model_provider: ModelProvider,
    ) -> None:
        definition.validate()
        if not definition.enabled or definition.deployment_state.value not in {"SHADOW", "DESIGNED"}:
            raise ValueError("MVL agent must be enabled in DESIGNED/SHADOW state")
        self.definition = definition
        self.journal = journal
        self.retrieval_provider = retrieval_provider
        self.model_provider = model_provider

    def start(
        self,
        *,
        job_type: str,
        objective: str,
        input_payload: Mapping[str, Any],
        validation_payload: Mapping[str, Any],
    ) -> RunEnvelope:
        assert_no_secret_material(input_payload)
        assert_no_secret_material(validation_payload)
        run_id = f"run_{uuid.uuid4().hex}"
        envelope = RunEnvelope(
            run_id=run_id,
            agent_id=self.definition.agent_id,
            agent_version=self.definition.version,
            job_type=job_type,
            environment=self.journal.environment,
            objective=objective,
            input_hash=canonical_hash(input_payload),
            validation_hash=canonical_hash(validation_payload),
        )
        envelope.validate(self.definition)
        self.journal.append(run_id, "RUN_CREATED", {
            "status": RunStatus.CREATED.value,
            "envelope": asdict(envelope),
            "input_payload": dict(input_payload),
            "validation_payload": dict(validation_payload),
            "retrieval_count": 0,
            "model_calls": 0,
            "tool_calls": 0,
            "cost_usd": 0.0,
        })
        return envelope

    def retrieve(self, run_id: str, query: str) -> list[Mapping[str, Any]]:
        state = self._active_state(run_id)
        if not query.strip():
            raise ValueError("retrieval query is required")
        self.journal.append(run_id, "RETRIEVAL_STARTED", {"status": RunStatus.RETRIEVING.value, "query_hash": canonical_hash(query)})
        rows = list(self.retrieval_provider(run_id, query))
        refs: list[str] = []
        sanitized: list[Mapping[str, Any]] = []
        for index, row in enumerate(rows):
            assert_no_secret_material(row)
            ref = str(row.get("ref") or row.get("id") or f"retrieval_{index}")
            refs.append(ref)
            sanitized.append(dict(row))
        self.journal.append(run_id, "RETRIEVAL_COMPLETED", {
            "status": RunStatus.READY_TO_REASON.value,
            "retrieval_count": len(refs),
            "retrieval_refs": refs,
            "retrieval_hash": canonical_hash(sanitized),
            "checkpoint": "retrieval_complete",
        })
        return sanitized

    def invoke_tool(self, run_id: str, tool_name: str, arguments: Mapping[str, Any], executor: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> Mapping[str, Any]:
        state = self._active_state(run_id)
        request = ToolRequest(run_id=run_id, tool_name=tool_name, arguments=arguments, environment=self.journal.environment)
        evaluation = ToolPolicy.evaluate(self.definition, request)
        next_count = int(state.get("tool_calls") or 0) + 1
        if next_count > self.definition.budget.max_tool_calls:
            evaluation = type(evaluation)(ToolDecision.DENY, "tool-call budget exhausted")
        self.journal.append(run_id, "TOOL_EVALUATED", {
            "tool_name": tool_name,
            "arguments_hash": request.arguments_hash,
            "decision": evaluation.decision.value,
            "reason": evaluation.reason,
            "tool_calls": next_count if evaluation.decision is ToolDecision.ALLOW else int(state.get("tool_calls") or 0),
        })
        if evaluation.decision is ToolDecision.DENY:
            raise PermissionError(evaluation.reason)
        assert_no_secret_material(arguments)
        result = dict(executor(arguments))
        assert_no_secret_material(result)
        self.journal.append(run_id, "TOOL_COMPLETED", {
            "tool_name": tool_name,
            "result_hash": canonical_hash(result),
            "checkpoint": f"tool:{tool_name}",
        })
        return result

    def reason(
        self,
        run_id: str,
        *,
        prompt_version: str,
        provider_family: str,
        model: str,
        request_payload: Mapping[str, Any],
        cost_usd: float = 0.0,
    ) -> Mapping[str, Any]:
        state = self._active_state(run_id)
        retrieval_refs = tuple(state.get("retrieval_refs") or ())
        if self.definition.retrieval_required and not retrieval_refs:
            raise RuntimeError("retrieval-before-reasoning gate failed")
        if cost_usd < 0:
            raise ValueError("cost_usd must be non-negative")
        next_calls = int(state.get("model_calls") or 0) + 1
        next_cost = float(state.get("cost_usd") or 0.0) + cost_usd
        if next_calls > self.definition.budget.max_model_calls:
            raise RuntimeError("model-call budget exhausted")
        if next_cost > self.definition.budget.max_cost_usd:
            raise RuntimeError("model-cost budget exhausted")
        assert_no_secret_material(request_payload)
        self.journal.append(run_id, "MODEL_STARTED", {
            "status": RunStatus.REASONING.value,
            "prompt_version": prompt_version,
            "provider_family": provider_family,
            "model": model,
            "request_hash": canonical_hash(request_payload),
            "model_calls": next_calls,
            "cost_usd": next_cost,
        })
        output = dict(self.model_provider(run_id, request_payload))
        assert_no_secret_material(output)
        self.journal.append(run_id, "MODEL_COMPLETED", {
            "status": RunStatus.REVIEW_REQUIRED.value,
            "output_hash": canonical_hash(output),
            "checkpoint": "model_complete",
        })
        return output

    def create_artifact(
        self,
        run_id: str,
        *,
        artifact_type: str,
        payload: Mapping[str, Any],
        prompt_version: str,
        provider_family: str,
        model: str,
    ) -> Artifact:
        state = self._active_state(run_id)
        envelope = state.get("envelope") or {}
        artifact = Artifact(
            artifact_id=f"artifact_{uuid.uuid4().hex}",
            run_id=run_id,
            producer_agent_id=self.definition.agent_id,
            artifact_type=artifact_type,
            payload=dict(payload),
            input_hash=str(envelope.get("input_hash") or ""),
            validation_hash=str(envelope.get("validation_hash") or ""),
            retrieval_refs=tuple(state.get("retrieval_refs") or ()),
            prompt_version=prompt_version,
            provider_family=provider_family,
            model=model,
        )
        assert_no_secret_material(payload)
        artifact.validate(self.definition.retrieval_required)
        self.journal.append(run_id, "ARTIFACT_CREATED", {
            "status": RunStatus.REVIEW_REQUIRED.value,
            "artifact": asdict(artifact),
            "artifact_hash": artifact.payload_hash,
            "checkpoint": "artifact_created",
        })
        return artifact

    def record_review(self, run_id: str, artifact: Artifact, reviewer_agent_id: str, verdict: ReviewVerdict, findings: Sequence[str]) -> Review:
        self._active_state(run_id)
        review = Review(
            review_id=f"review_{uuid.uuid4().hex}",
            artifact_id=artifact.artifact_id,
            producer_agent_id=artifact.producer_agent_id,
            reviewer_agent_id=reviewer_agent_id,
            verdict=verdict,
            findings=tuple(str(item) for item in findings),
            artifact_hash=artifact.payload_hash,
        )
        review.validate()
        self.journal.append(run_id, "REVIEW_RECORDED", {
            "review": asdict(review),
            "review_verdict": verdict.value,
            "checkpoint": "review_recorded",
        })
        return review

    def record_score(self, run_id: str, artifact: Artifact, scorer_agent_id: str, dimensions: Mapping[str, float], outcome_ref: str | None = None) -> Score:
        self._active_state(run_id)
        score = Score(
            score_id=f"score_{uuid.uuid4().hex}",
            artifact_id=artifact.artifact_id,
            producer_agent_id=artifact.producer_agent_id,
            scorer_agent_id=scorer_agent_id,
            dimensions=dict(dimensions),
            outcome_ref=outcome_ref,
        )
        score.validate()
        self.journal.append(run_id, "SCORE_RECORDED", {"score": asdict(score), "checkpoint": "score_recorded"})
        return score

    def complete(self, run_id: str) -> None:
        state = self._active_state(run_id)
        if not state.get("artifact"):
            raise RuntimeError("cannot complete a run without an immutable artifact")
        if not state.get("review"):
            raise RuntimeError("cannot complete a run without independent review")
        self.journal.append(run_id, "RUN_COMPLETED", {"status": RunStatus.COMPLETED.value, "completed_at": utc_now(), "checkpoint": "complete"})

    def cancel(self, run_id: str, reason: str) -> None:
        state = self.journal.replay(run_id)
        if state.get("status") in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value}:
            raise RuntimeError("terminal run cannot be cancelled")
        self.journal.append(run_id, "RUN_CANCELLED", {"status": RunStatus.CANCELLED.value, "cancellation_reason": reason, "cancelled_at": utc_now()})

    def resume(self, run_id: str) -> Mapping[str, Any]:
        state = self.journal.replay(run_id)
        if state.get("status") == RunStatus.CANCELLED.value:
            raise RuntimeError("cancelled run requires a new run envelope")
        if state.get("status") == RunStatus.COMPLETED.value:
            return state
        self.journal.append(run_id, "RUN_RESUMED", {"status": state.get("status", RunStatus.CREATED.value), "resumed_at": utc_now(), "resume_from": state.get("checkpoint")})
        return self.journal.replay(run_id)

    def status(self, run_id: str) -> Mapping[str, Any]:
        return self.journal.replay(run_id)

    def _active_state(self, run_id: str) -> dict[str, Any]:
        state = self.journal.replay(run_id)
        if state.get("sequence", 0) == 0:
            raise KeyError(f"unknown run: {run_id}")
        if state.get("status") in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value, RunStatus.FAILED.value}:
            raise RuntimeError(f"run is terminal: {state.get('status')}")
        return state
