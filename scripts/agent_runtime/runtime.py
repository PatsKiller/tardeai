from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone
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
from .persistence import PersistenceError, RunPersistence, TerminalRunError

RetrievalProvider = Callable[[str, str], Sequence[Mapping[str, Any]]]
ModelProvider = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
Clock = Callable[[], datetime]

_TERMINAL = {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value, RunStatus.FAILED.value}


class MvlRuntime:
    """Durable shadow implementation of the first agentic loop.

    When a ``RunPersistence`` adapter is injected, that adapter is the *single
    authoritative* source of run lifecycle state: every transition, counter,
    checkpoint, budget read, terminal/resume gate and reconstruction goes through the
    persistence contract, and ``ShadowRunJournal`` is not used. Without persistence,
    the runtime is journal-only (unchanged, backward-compatible). It never exposes
    arbitrary shell, production database, broker, order, approval, 2FA, credential, or
    config-promotion methods.
    """

    def __init__(
        self,
        definition: AgentDefinition,
        journal: ShadowRunJournal,
        retrieval_provider: RetrievalProvider,
        model_provider: ModelProvider,
        clock: Clock | None = None,
        persistence: RunPersistence | None = None,
    ) -> None:
        definition.validate()
        if not definition.enabled or definition.deployment_state.value not in {"SHADOW", "DESIGNED"}:
            raise ValueError("MVL agent must be enabled in DESIGNED/SHADOW state")
        self.definition = definition
        self.journal = journal
        self.retrieval_provider = retrieval_provider
        self.model_provider = model_provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.persistence = persistence

    @property
    def _persist(self) -> bool:
        return self.persistence is not None

    # ---- authoritative state read ----------------------------------------
    def _read_state(self, run_id: str) -> dict[str, Any]:
        """Normalized run state from the single authority (persistence or journal)."""
        if not self._persist:
            return dict(self.journal.replay(run_id))
        try:
            rs = self.persistence.reconstruct(run_id)
        except PersistenceError as exc:
            if "unknown run" in str(exc):
                raise KeyError(f"unknown run: {run_id}") from exc
            raise
        return {
            "sequence": rs.sequence,
            "status": rs.status,
            "checkpoint": rs.checkpoint,
            "retrieval_count": rs.retrieval_count,
            "retrieval_refs": list(rs.retrieval_refs),
            "model_calls": rs.model_calls,
            "tool_calls": rs.tool_calls,
            "cost_usd": rs.cost_usd,
            "envelope": {
                "input_hash": rs.input_hash,
                "validation_hash": rs.validation_hash,
                "created_at": rs.created_at,
            },
            "artifact": bool(rs.artifacts),
            "review": bool(rs.reviews),
            "score": bool(rs.scores),
            "artifacts": list(rs.artifacts),
            "reviews": list(rs.reviews),
            "scores": list(rs.scores),
            "completed_at": rs.completed_at,
            "cancellation_reason": rs.cancellation_reason,
            "failure_code": rs.failure_code,
        }

    def _known(self, state: Mapping[str, Any]) -> bool:
        return int(state.get("sequence", 0)) > 0

    # ---- lifecycle -------------------------------------------------------
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
            created_at=self._now().isoformat(),
        )
        envelope.validate(self.definition)
        if self._persist:
            # Persistence is authoritative: identity is created durably; the journal is
            # not written. A persistence failure propagates (never silently falls back).
            self.persistence.create_run(envelope, self.definition.budget)
            return envelope
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
        self._active_state(run_id)
        if not query.strip():
            raise ValueError("retrieval query is required")
        if self._persist:
            self.persistence.record_retrieval_started(run_id, query_hash=canonical_hash(query))
            rows = list(self.retrieval_provider(run_id, query))
            refs, sanitized = self._sanitize_retrieval(rows)
            self.persistence.record_retrieval_completed(run_id, refs=refs, retrieval_hash=canonical_hash(sanitized))
            return sanitized
        self.journal.append(run_id, "RETRIEVAL_STARTED", {"status": RunStatus.RETRIEVING.value, "query_hash": canonical_hash(query)})
        rows = list(self.retrieval_provider(run_id, query))
        self._active_state(run_id)
        refs, sanitized = self._sanitize_retrieval(rows)
        self.journal.append(run_id, "RETRIEVAL_COMPLETED", {
            "status": RunStatus.READY_TO_REASON.value,
            "retrieval_count": len(refs),
            "retrieval_refs": refs,
            "retrieval_hash": canonical_hash(sanitized),
            "checkpoint": "retrieval_complete",
        })
        return sanitized

    def _sanitize_retrieval(self, rows: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[Mapping[str, Any]]]:
        refs: list[str] = []
        sanitized: list[Mapping[str, Any]] = []
        for index, row in enumerate(rows):
            assert_no_secret_material(row)
            refs.append(str(row.get("ref") or row.get("id") or f"retrieval_{index}"))
            sanitized.append(dict(row))
        return refs, sanitized

    def invoke_tool(self, run_id: str, tool_name: str, arguments: Mapping[str, Any], executor: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> Mapping[str, Any]:
        state = self._active_state(run_id)
        request = ToolRequest(run_id=run_id, tool_name=tool_name, arguments=arguments, environment=self.journal.environment)
        evaluation = ToolPolicy.evaluate(self.definition, request)
        next_count = int(state.get("tool_calls") or 0) + 1
        if self._persist:
            # Durable prepare (PROPOSED/DECISION/STARTED + atomic budget reservation under
            # the run lock) commits BEFORE the executor runs, so an external side effect can
            # never occur without durable started evidence. prepare is authoritative for the
            # budget decision (it may downgrade ALLOW->DENY when the budget is exhausted).
            started = self._now().isoformat()
            prep = self.persistence.prepare_tool_call(
                run_id, agent_id=self.definition.agent_id, tool_name=tool_name,
                decision=evaluation.decision.value, decision_reason=evaluation.reason,
                arguments_hash=request.arguments_hash, started_at=started)
            if prep.decision == "DENY":
                raise PermissionError(prep.reason)
            assert_no_secret_material(arguments)
            try:
                result = dict(executor(arguments))
                assert_no_secret_material(result)
            except Exception:
                # Terminal FAILED is attempted; the executor exception propagates. If this
                # durable write itself fails, the started/in-flight evidence remains.
                self.persistence.finish_tool_call(
                    run_id, tool_call_id=prep.tool_call_id, agent_id=self.definition.agent_id, tool_name=tool_name,
                    decision_reason=prep.reason, arguments_hash=request.arguments_hash,
                    result_hash=None, started_at=started, completed_at=self._now().isoformat(), terminal_state="failed")
                raise
            self.persistence.finish_tool_call(
                run_id, tool_call_id=prep.tool_call_id, agent_id=self.definition.agent_id, tool_name=tool_name,
                decision_reason=prep.reason, arguments_hash=request.arguments_hash,
                result_hash=canonical_hash(result), started_at=started, completed_at=self._now().isoformat(), terminal_state="completed")
            return result
        if evaluation.decision is ToolDecision.ALLOW and next_count > self.definition.budget.max_tool_calls:
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
        self._active_state(run_id)
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
        if self._persist:
            # Durable MODEL_STARTED (counter + cost) commits BEFORE the provider is called,
            # so a persistence failure fails closed before the side effect.
            self.persistence.record_model_started(run_id, prompt_version=prompt_version, provider_family=provider_family,
                                                  model=model, request_hash=canonical_hash(request_payload), cost_usd=cost_usd)
            output = dict(self.model_provider(run_id, request_payload))
            assert_no_secret_material(output)
            self.persistence.record_model_completed(run_id, output_hash=canonical_hash(output))
            return output
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
        self._active_state(run_id)
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
        if self._persist:
            self.persistence.record_artifact(artifact, retrieval_required=self.definition.retrieval_required)
            return artifact
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
        if self._persist:
            self.persistence.record_review(review)
            return review
        self.journal.append(run_id, "REVIEW_RECORDED", {
            "review": asdict(review),
            "review_verdict": verdict.value,
            "checkpoint": "review_recorded",
        })
        return review

    def record_score(self, run_id: str, artifact: Artifact, scorer_agent_id: str, dimensions: Mapping[str, float], outcome_ref: str | None = None) -> Score:
        # Independent Darwin scoring is permitted even after a run terminates; it only
        # requires that the run exists.
        state = self._read_state(run_id)
        if not self._known(state):
            raise KeyError(f"unknown run: {run_id}")
        score = Score(
            score_id=f"score_{uuid.uuid4().hex}",
            artifact_id=artifact.artifact_id,
            producer_agent_id=artifact.producer_agent_id,
            scorer_agent_id=scorer_agent_id,
            dimensions=dict(dimensions),
            outcome_ref=outcome_ref,
        )
        score.validate()
        if self._persist:
            self.persistence.record_score(score)
            return score
        self.journal.append(run_id, "SCORE_RECORDED", {"score": asdict(score), "checkpoint": "score_recorded"})
        return score

    def complete(self, run_id: str) -> None:
        state = self._active_state(run_id)
        if not state.get("artifact"):
            raise RuntimeError("cannot complete a run without an immutable artifact")
        if not state.get("review"):
            raise RuntimeError("cannot complete a run without independent review")
        if self._persist:
            self.persistence.complete_run(run_id)
            return
        self.journal.append(run_id, "RUN_COMPLETED", {"status": RunStatus.COMPLETED.value, "completed_at": self._now().isoformat(), "checkpoint": "complete"})

    def fail(self, run_id: str, reason: str, failure_code: str = "RUNTIME_FAILURE") -> None:
        state = self._read_state(run_id)
        if not self._known(state):
            raise KeyError(f"unknown run: {run_id}")
        if state.get("status") in _TERMINAL:
            raise RuntimeError(f"run is terminal: {state.get('status')}")
        if self._persist:
            self.persistence.fail_run(run_id, reason, failure_code)
            return
        self.journal.append(run_id, "RUN_FAILED", {
            "status": RunStatus.FAILED.value,
            "failure_code": failure_code,
            "failure_reason": reason,
            "completed_at": self._now().isoformat(),
            "checkpoint": state.get("checkpoint"),
        })

    def cancel(self, run_id: str, reason: str) -> None:
        self._active_state(run_id)
        if self._persist:
            self.persistence.cancel_run(run_id, reason)
            return
        self.journal.append(run_id, "RUN_CANCELLED", {"status": RunStatus.CANCELLED.value, "cancellation_reason": reason, "cancelled_at": self._now().isoformat()})

    def resume(self, run_id: str) -> Mapping[str, Any]:
        state = self._read_state(run_id)
        if not self._known(state):
            raise KeyError(f"unknown run: {run_id}")
        if state.get("status") == RunStatus.CANCELLED.value:
            raise RuntimeError("cancelled run requires a new run envelope")
        if state.get("status") == RunStatus.FAILED.value:
            raise RuntimeError("failed run requires a new run envelope")
        if state.get("status") == RunStatus.COMPLETED.value:
            return state
        self._assert_within_deadline(run_id, state)
        if self._persist:
            self.persistence.resume_run(run_id)
            return self._read_state(run_id)
        self.journal.append(run_id, "RUN_RESUMED", {"status": state.get("status", RunStatus.CREATED.value), "resumed_at": self._now().isoformat(), "resume_from": state.get("checkpoint")})
        return self.journal.replay(run_id)

    def status(self, run_id: str) -> Mapping[str, Any]:
        return self._read_state(run_id)

    def _active_state(self, run_id: str) -> dict[str, Any]:
        state = self._read_state(run_id)
        if not self._known(state):
            raise KeyError(f"unknown run: {run_id}")
        if state.get("status") in _TERMINAL:
            raise RuntimeError(f"run is terminal: {state.get('status')}")
        self._assert_within_deadline(run_id, state)
        return state

    def _assert_within_deadline(self, run_id: str, state: Mapping[str, Any]) -> None:
        envelope = state.get("envelope") or {}
        created_at_raw = str(envelope.get("created_at") or "")
        if not created_at_raw:
            self.fail(run_id, "run envelope is missing created_at", "INVALID_RUN_ENVELOPE")
            raise RuntimeError("run envelope is missing created_at")
        try:
            created_at = datetime.fromisoformat(created_at_raw)
        except ValueError as exc:
            self.fail(run_id, "run envelope created_at is invalid", "INVALID_RUN_ENVELOPE")
            raise RuntimeError("run envelope created_at is invalid") from exc
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        elapsed_seconds = max(0.0, (self._now() - created_at.astimezone(timezone.utc)).total_seconds())
        if elapsed_seconds <= self.definition.budget.deadline_seconds:
            return
        if self._persist:
            self.persistence.record_deadline_exceeded(run_id, deadline_seconds=self.definition.budget.deadline_seconds, elapsed_seconds=elapsed_seconds)
        else:
            self.journal.append(run_id, "RUN_FAILED", {
                "status": RunStatus.FAILED.value,
                "failure_code": "DEADLINE_EXCEEDED",
                "failure_reason": "agent runtime deadline exceeded",
                "deadline_seconds": self.definition.budget.deadline_seconds,
                "elapsed_seconds": elapsed_seconds,
                "completed_at": self._now().isoformat(),
                "checkpoint": state.get("checkpoint"),
            })
        raise TimeoutError("agent runtime deadline exceeded")

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
