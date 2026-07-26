"""Persistence protocol and backends for the governed agent runtime (MVL).

LAB/SHADOW only. No broker, order, approval, 2FA, scheduler, service, provider, or
config-promotion authority. This module never imports a database driver: the caller
injects a DB-API 2.0 *connection factory* whose runtime credential may reach only
``agentic_runtime``; the migration identity is never required here.

Correctness properties (all enforced in the shared base so both backends agree):

* Persisted-truth binding — idempotent create compares the *complete* immutable run
  envelope and budget; reviews/scores are bound to the *persisted* artifact's run and
  producer, never to a caller-claimed producer.
* Conflict-safe idempotency — a duplicate stable identity is a no-op only when every
  immutable field matches; a conflicting duplicate raises IdempotencyConflictError. An
  artifact payload-hash conflict returns the already-persisted artifact id.
* Append-only journal — run events are immutable rows in ``agent_artifacts`` (reserved
  ``__run_event__`` type), each carrying a per-run sequence and previous-hash chain and
  keyed by its own event hash. The mutable ``agent_runs.checkpoint`` is only a pointer
  to the immutable event tail; reconstruction validates the chain from the immutable
  rows, so the runtime writer cannot silently rewrite history.
* Durable tool lifecycle — proposed / decision / started / terminal stages are separate
  durable events, so a crash mid-call leaves reconstructable in-flight evidence.
* Transactional & fail-closed — one connection and one explicit transaction per
  operation (autocommit off), bounded statement_timeout, parameterized SQL,
  ``SELECT ... FOR UPDATE`` on the run row before advancing its chain, rollback on any
  failure. The in-memory backend is copy-on-write so it rolls back identically.
* Producer separation — no self-review / self-score, enforced in application logic and
  by the database CHECK constraints. Post-run independent review and Darwin scoring are
  permitted (append-only) without resuming or mutating execution state.
* No secrets — every payload passes ``assert_no_secret_material`` before persistence.
"""

from __future__ import annotations

import copy
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import (
    Artifact,
    BudgetPolicy,
    Environment,
    Review,
    RunEnvelope,
    RunStatus,
    Score,
    assert_no_secret_material,
    canonical_hash,
    canonical_json,
    utc_now,
)

SCHEMA_VERSION = "agentic_runtime.mvl.0001"
JOURNAL_CONTRACT = "agent-runtime-journal-v1"
GENESIS_HASH = "0" * 64
DEFAULT_STATEMENT_TIMEOUT_MS = 15_000
MAX_JOURNAL_EVENTS = 100_000
RUN_EVENT_TYPE = "__run_event__"
RUNTIME_PRODUCER = "__runtime__"

DEFAULT_RUNTIME_ROLE_ALLOWLIST = ("agentic_runtime_lab_rw", "agentic_runtime_shadow_rw")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EXEC_TERMINAL = frozenset({RunStatus.CANCELLED.value, RunStatus.FAILED.value, RunStatus.COMPLETED.value})


class PersistenceError(RuntimeError):
    """Raised when a persistence invariant is violated or a write fails."""


class TerminalRunError(PersistenceError):
    """Raised when terminal execution state is mutated or resumed."""


class IdempotencyConflictError(PersistenceError):
    """Raised when a stable identity is reused with a changed immutable field."""


class RuntimeIdentityError(PersistenceError):
    """Raised when the connected identity is not an approved runtime writer."""


@dataclass(frozen=True)
class JournalEvent:
    run_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    created_at: str
    previous_hash: str
    event_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "sequence": self.sequence, "event_type": self.event_type,
            "payload": dict(self.payload), "created_at": self.created_at,
            "previous_hash": self.previous_hash, "event_hash": self.event_hash,
        }


@dataclass(frozen=True)
class RunState:
    run_id: str
    status: str
    sequence: int
    head_hash: str
    checkpoint: str | None
    retrieval_count: int
    model_calls: int
    tool_calls: int
    cost_usd: float
    artifacts: tuple[str, ...]
    tool_calls_ids: tuple[str, ...]
    reviews: tuple[str, ...]
    scores: tuple[str, ...]
    cancellation_reason: str | None
    completed_at: str | None
    updated_at: str | None
    retrieval_refs: tuple[str, ...] = ()
    input_hash: str = ""
    validation_hash: str = ""
    environment: str = ""
    created_at: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class ToolPreparation:
    """Result of the pre-execution tool boundary: the durable identity + effective decision."""

    tool_call_id: str
    decision: str
    reason: str
    started_at: str


def event_body(run_id: str, sequence: int, event_type: str, payload: Mapping[str, Any], created_at: str, previous_hash: str) -> dict[str, Any]:
    return {
        "run_id": run_id, "sequence": sequence, "event_type": event_type,
        "payload": dict(payload), "created_at": created_at, "previous_hash": previous_hash,
    }


def compute_event_hash(body: Mapping[str, Any]) -> str:
    return canonical_hash(body)


def derive_id(*parts: object) -> str:
    return canonical_hash(["agentic_runtime.id", *[str(part) for part in parts]])


def _no_secret(payload: Any) -> None:
    """Reject secret-like material, surfacing a PersistenceError (not a bare ValueError)."""
    try:
        assert_no_secret_material(payload)
    except ValueError as exc:
        raise PersistenceError(str(exc)) from exc


@runtime_checkable
class RunPersistence(Protocol):
    def create_run(self, envelope: RunEnvelope, budget: BudgetPolicy) -> RunState: ...
    def record_retrieval_started(self, run_id: str, *, query_hash: str) -> RunState: ...
    def record_retrieval_completed(self, run_id: str, *, refs: Sequence[str], retrieval_hash: str) -> RunState: ...
    def record_model_started(self, run_id: str, *, prompt_version: str, provider_family: str, model: str, request_hash: str, cost_usd: float = 0.0) -> RunState: ...
    def record_model_completed(self, run_id: str, *, output_hash: str) -> RunState: ...
    def prepare_tool_call(self, run_id: str, *, agent_id: str, tool_name: str, decision: str, decision_reason: str, arguments_hash: str, started_at: str) -> "ToolPreparation": ...
    def finish_tool_call(self, run_id: str, *, tool_call_id: str, agent_id: str, tool_name: str, decision_reason: str, arguments_hash: str, result_hash: str | None, started_at: str, completed_at: str | None, terminal_state: str) -> str: ...
    def record_tool_lifecycle(self, run_id: str, *, agent_id: str, tool_name: str, decision: str, decision_reason: str, arguments_hash: str, result_hash: str | None, started_at: str, completed_at: str | None, terminal_state: str) -> str: ...
    def record_artifact(self, artifact: Artifact, *, retrieval_required: bool = True) -> str: ...
    def record_review(self, review: Review) -> str: ...
    def record_score(self, score: Score) -> str: ...
    def record_deadline_exceeded(self, run_id: str, *, deadline_seconds: int, elapsed_seconds: float) -> RunState: ...
    def resume_run(self, run_id: str) -> RunState: ...
    def complete_run(self, run_id: str) -> RunState: ...
    def cancel_run(self, run_id: str, reason: str) -> RunState: ...
    def fail_run(self, run_id: str, reason: str, failure_code: str = "RUNTIME_FAILURE") -> RunState: ...
    def reconstruct(self, run_id: str) -> RunState: ...
    def journal(self, run_id: str) -> list[JournalEvent]: ...


class _UnitOfWork:
    """Backend transaction context. All transaction-scoped state lives here."""

    def load_control(self, run_id: str, *, lock: bool) -> dict[str, Any] | None:  # pragma: no cover
        raise NotImplementedError

    def insert_control(self, row: Mapping[str, Any]) -> bool:  # pragma: no cover
        raise NotImplementedError

    def save_control(self, run_id: str, row: Mapping[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError

    def insert_row(self, table: str, conflict_key: Mapping[str, Any], row: Mapping[str, Any]) -> bool:  # pragma: no cover
        raise NotImplementedError

    def get_row(self, table: str, key: Mapping[str, Any]) -> dict[str, Any] | None:  # pragma: no cover
        raise NotImplementedError

    def rows_for_run(self, table: str, run_id: str) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def commit(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def rollback(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        raise NotImplementedError


class _PersistenceBase:
    def __init__(self, *, clock=utc_now) -> None:
        self._clock = clock

    def _unit(self) -> _UnitOfWork:  # pragma: no cover
        raise NotImplementedError

    @contextmanager
    def _work(self) -> Iterator[_UnitOfWork]:
        uow = self._unit()
        try:
            yield uow
            uow.commit()
        except PersistenceError:
            uow.rollback()
            raise
        except Exception as exc:
            uow.rollback()
            raise PersistenceError(f"persistence operation failed: {type(exc).__name__}: {exc}") from exc
        finally:
            uow.close()

    # ---- append-only journal in agent_artifacts (RUN_EVENT rows) ----------
    def _load_events(self, uow: _UnitOfWork, run_id: str) -> list[dict[str, Any]]:
        rows = [r for r in uow.rows_for_run("agent_artifacts", run_id) if r.get("artifact_type") == RUN_EVENT_TYPE]
        rows.sort(key=lambda r: int(r["payload"]["sequence"]))
        previous = GENESIS_HASH
        for index, row in enumerate(rows, start=1):
            body = row["payload"]
            if int(body["sequence"]) != index or body["previous_hash"] != previous:
                raise PersistenceError(f"run {run_id} journal chain broken at sequence {index}")
            expected = compute_event_hash(event_body(run_id, index, body["event_type"], body["payload"], body["created_at"], previous))
            if expected != row["payload_hash"]:
                raise PersistenceError(f"run {run_id} journal event {index} hash mismatch")
            previous = row["payload_hash"]
        return rows

    def _append_event(self, uow: _UnitOfWork, control: dict[str, Any], event_type: str, payload: Mapping[str, Any], *, status: str | None = None, checkpoint: str | None = None) -> str:
        _no_secret(payload)
        run_id = control["run_id"]
        events = self._load_events(uow, run_id)
        if len(events) >= MAX_JOURNAL_EVENTS:
            raise PersistenceError("run journal exceeds bounded event budget")
        sequence = len(events) + 1
        previous_hash = events[-1]["payload_hash"] if events else GENESIS_HASH
        created_at = self._clock()
        inner = dict(payload)
        event_hash = compute_event_hash(event_body(run_id, sequence, event_type, inner, created_at, previous_hash))
        uow.insert_row(
            "agent_artifacts",
            {"run_id": run_id, "payload_hash": event_hash},
            {
                "artifact_id": derive_id("run_event", run_id, sequence), "run_id": run_id,
                "producer_agent_id": RUNTIME_PRODUCER, "artifact_type": RUN_EVENT_TYPE,
                "payload": {"sequence": sequence, "event_type": event_type, "payload": inner, "previous_hash": previous_hash, "created_at": created_at},
                "payload_hash": event_hash, "input_hash": control["input_hash"], "validation_hash": control["validation_hash"],
                "retrieval_refs": [], "prompt_version": "runtime", "provider_family": "runtime", "model": "runtime", "created_at": created_at,
            },
        )
        control["checkpoint_seq"] = sequence
        control["head_hash"] = event_hash
        control["updated_at"] = created_at
        if checkpoint is not None:
            control["checkpoint_label"] = checkpoint
        if status is not None:
            control["status"] = status
        return event_hash

    def _bump(self, control: dict[str, Any], field: str, amount: float = 1) -> None:
        control[field] = (control.get(field, 0) or 0) + amount

    def _state(self, uow: _UnitOfWork, control: dict[str, Any]) -> RunState:
        run_id = control["run_id"]
        artifacts = tuple(r["artifact_id"] for r in sorted((r for r in uow.rows_for_run("agent_artifacts", run_id) if r.get("artifact_type") != RUN_EVENT_TYPE), key=lambda r: r.get("created_at") or ""))
        tool_ids = tuple(r["tool_call_id"] for r in sorted(uow.rows_for_run("agent_tool_calls", run_id), key=lambda r: r.get("started_at") or ""))
        reviews = tuple(r["review_id"] for r in sorted(uow.rows_for_run("agent_reviews", run_id), key=lambda r: r.get("created_at") or ""))
        scores = tuple(r["score_id"] for r in sorted(uow.rows_for_run("agent_scores", run_id), key=lambda r: r.get("created_at") or ""))
        return RunState(
            run_id=run_id, status=control.get("status", RunStatus.CREATED.value),
            sequence=int(control.get("checkpoint_seq", 0)), head_hash=control.get("head_hash", GENESIS_HASH),
            checkpoint=control.get("checkpoint_label"), retrieval_count=int(control.get("retrieval_count", 0)),
            model_calls=int(control.get("model_calls", 0)), tool_calls=int(control.get("tool_calls", 0)),
            cost_usd=float(control.get("cost_usd", 0.0)), artifacts=artifacts, tool_calls_ids=tool_ids,
            reviews=reviews, scores=scores, cancellation_reason=control.get("cancellation_reason"),
            completed_at=control.get("completed_at"), updated_at=control.get("updated_at"),
            retrieval_refs=tuple(control.get("retrieval_refs") or ()),
            input_hash=control.get("input_hash", ""), validation_hash=control.get("validation_hash", ""),
            environment=control.get("environment", ""), created_at=control.get("created_at"),
            failure_code=control.get("failure_code"),
        )

    def _require_run(self, uow: _UnitOfWork, run_id: str, *, lock: bool = False) -> dict[str, Any]:
        control = uow.load_control(run_id, lock=lock)
        if control is None:
            raise PersistenceError(f"unknown run: {run_id}")
        return control

    def _require_open_exec(self, uow: _UnitOfWork, run_id: str) -> dict[str, Any]:
        control = self._require_run(uow, run_id, lock=True)
        if control.get("status") in _EXEC_TERMINAL:
            raise TerminalRunError(f"run execution is terminal: {control.get('status')}")
        return control

    # ---- create -----------------------------------------------------------
    def create_run(self, envelope: RunEnvelope, budget: BudgetPolicy) -> RunState:
        budget.validate()
        if envelope.environment not in {Environment.LAB, Environment.SHADOW}:
            raise PersistenceError("MVL persistence is LAB/SHADOW only")
        if not _HEX64.match(envelope.input_hash) or not _HEX64.match(envelope.validation_hash):
            raise PersistenceError("run hashes must be sha256")
        immutable = {
            "agent_id": envelope.agent_id, "agent_version": envelope.agent_version,
            "job_type": envelope.job_type, "environment": envelope.environment.value,
            "objective_hash": canonical_hash(envelope.objective),
            "input_hash": envelope.input_hash, "validation_hash": envelope.validation_hash,
            "budget": {"max_model_calls": budget.max_model_calls, "max_tool_calls": budget.max_tool_calls, "max_cost_usd": budget.max_cost_usd, "deadline_seconds": budget.deadline_seconds},
        }
        with self._work() as uow:
            existing = uow.load_control(envelope.run_id, lock=True)
            if existing is not None:
                for key, value in immutable.items():
                    if existing.get(key) != value:
                        raise IdempotencyConflictError(f"run_id {envelope.run_id} exists with different {key}")
                # Envelope creation timestamp is part of the immutable identity: reusing a run_id
                # with a changed created_at is a conflict, not an idempotent replay.
                if envelope.created_at is not None and existing.get("created_at") != envelope.created_at:
                    raise IdempotencyConflictError(f"run_id {envelope.run_id} exists with different created_at")
                return self._state(uow, existing)
            now = self._clock()
            control: dict[str, Any] = {
                "run_id": envelope.run_id, **immutable, "objective": envelope.objective,
                "status": RunStatus.CREATED.value, "retrieval_count": 0, "model_calls": 0,
                "tool_calls": 0, "cost_usd": 0.0, "checkpoint_seq": 0, "head_hash": GENESIS_HASH,
                "checkpoint_label": None, "cancellation_reason": None, "completed_at": None,
                "started_at": now, "updated_at": now, "retrieval_refs": [],
                "created_at": envelope.created_at or now, "failure_code": None,
            }
            uow.insert_control(control)
            self._append_event(uow, control, "RUN_CREATED", {"status": RunStatus.CREATED.value, "objective_hash": immutable["objective_hash"]}, status=RunStatus.CREATED.value, checkpoint="created")
            uow.save_control(envelope.run_id, control)
            return self._state(uow, control)

    # ---- material artifact ------------------------------------------------
    def record_artifact(self, artifact: Artifact, *, retrieval_required: bool = True) -> str:
        artifact.validate(retrieval_required=retrieval_required)
        _no_secret(dict(artifact.payload))
        with self._work() as uow:
            control = self._require_open_exec(uow, artifact.run_id)
            if artifact.input_hash != control["input_hash"] or artifact.validation_hash != control["validation_hash"]:
                raise PersistenceError("artifact input/validation hash does not match the persisted run")
            existing = uow.get_row("agent_artifacts", {"run_id": artifact.run_id, "payload_hash": artifact.payload_hash})
            if existing is not None:
                return existing["artifact_id"]  # never the caller's new id
            uow.insert_row(
                "agent_artifacts", {"run_id": artifact.run_id, "payload_hash": artifact.payload_hash},
                {
                    "artifact_id": artifact.artifact_id, "run_id": artifact.run_id, "producer_agent_id": artifact.producer_agent_id,
                    "artifact_type": artifact.artifact_type, "payload": dict(artifact.payload), "payload_hash": artifact.payload_hash,
                    "input_hash": artifact.input_hash, "validation_hash": artifact.validation_hash, "retrieval_refs": list(artifact.retrieval_refs),
                    "prompt_version": artifact.prompt_version, "provider_family": artifact.provider_family, "model": artifact.model, "created_at": self._clock(),
                },
            )
            self._append_event(uow, control, "ARTIFACT_CREATED", {"artifact_id": artifact.artifact_id, "payload_hash": artifact.payload_hash, "producer_agent_id": artifact.producer_agent_id}, status=RunStatus.REVIEW_REQUIRED.value, checkpoint="artifact_created")
            uow.save_control(artifact.run_id, control)
            return artifact.artifact_id

    # ---- durable tool lifecycle: prepare (before executor) + finish (after) ----
    def _prepared_tool_decision(self, events: list[dict[str, Any]], tool_call_id: str) -> str | None:
        for row in events:
            body = row["payload"]
            inner = body.get("payload") or {}
            if inner.get("tool_call_id") == tool_call_id:
                if body["event_type"] == "TOOL_STARTED":
                    return "ALLOW"
                if body["event_type"] == "TOOL_CANCELLED":
                    return "DENY"
        return None

    def prepare_tool_call(self, run_id: str, *, agent_id: str, tool_name: str, decision: str, decision_reason: str, arguments_hash: str, started_at: str) -> ToolPreparation:
        """Durably record TOOL_PROPOSED/DECISION (+ TOOL_STARTED for ALLOW, or the denied
        terminal for DENY) and reserve the tool-call budget under the run lock — all BEFORE
        the executor runs. Idempotent by the derived tool_call_id. Inserts no terminal row."""
        if decision not in {"ALLOW", "DENY"}:
            raise PersistenceError("tool decision must be ALLOW or DENY")
        if not _HEX64.match(arguments_hash):
            raise PersistenceError("tool arguments_hash must be sha256")
        tool_call_id = derive_id("tool_call", run_id, agent_id, tool_name, arguments_hash, started_at)
        with self._work() as uow:
            control = self._require_open_exec(uow, run_id)
            prepared = self._prepared_tool_decision(self._load_events(uow, run_id), tool_call_id)
            if prepared is not None:  # idempotent: this exact call was already prepared
                return ToolPreparation(tool_call_id=tool_call_id, decision=prepared, reason=decision_reason, started_at=started_at)
            effective, reason = decision, decision_reason
            if decision == "ALLOW":
                max_tool = int((control.get("budget") or {}).get("max_tool_calls", 0))
                if int(control.get("tool_calls", 0)) + 1 > max_tool:
                    effective, reason = "DENY", "tool-call budget exhausted"
            self._append_event(uow, control, "TOOL_PROPOSED", {"tool_call_id": tool_call_id, "tool_name": tool_name}, checkpoint=f"tool_proposed:{tool_name}")
            self._append_event(uow, control, "TOOL_DECISION", {"tool_call_id": tool_call_id, "decision": effective, "reason": reason})
            if effective == "ALLOW":
                self._append_event(uow, control, "TOOL_STARTED", {"tool_call_id": tool_call_id, "started_at": started_at}, checkpoint=f"tool_started:{tool_name}")
                self._bump(control, "tool_calls")  # reserve the budget under the run lock
            else:
                self._append_event(uow, control, "TOOL_CANCELLED", {"tool_call_id": tool_call_id, "reason": reason}, checkpoint=f"tool_denied:{tool_name}")
            uow.save_control(run_id, control)
            return ToolPreparation(tool_call_id=tool_call_id, decision=effective, reason=reason, started_at=started_at)

    def finish_tool_call(self, run_id: str, *, tool_call_id: str, agent_id: str, tool_name: str, decision_reason: str, arguments_hash: str, result_hash: str | None, started_at: str, completed_at: str | None, terminal_state: str) -> str:
        """Record only the ACTUAL terminal result of a PREPARED tool call: the append-only
        agent_tool_calls row + terminal journal event, transactionally. Idempotent for
        identical terminal evidence; rejects conflicting evidence; refuses to finish a call
        that has no durable prepared (TOOL_STARTED) lifecycle."""
        if terminal_state not in {"completed", "failed", "cancelled", "timeout"}:
            raise PersistenceError("terminal_state must be completed/failed/cancelled/timeout")
        if result_hash is not None and not _HEX64.match(result_hash):
            raise PersistenceError("tool result_hash must be sha256")
        with self._work() as uow:
            control = self._require_run(uow, run_id, lock=True)
            existing = uow.get_row("agent_tool_calls", {"tool_call_id": tool_call_id})
            if existing is not None:  # idempotent for identical evidence; conflict otherwise
                if existing.get("result_hash") != result_hash or existing.get("completed_at") != completed_at:
                    raise IdempotencyConflictError(f"tool_call {tool_call_id} exists with different terminal evidence")
                return tool_call_id
            if self._prepared_tool_decision(self._load_events(uow, run_id), tool_call_id) != "ALLOW":
                raise PersistenceError(f"tool_call {tool_call_id} was not durably prepared (no TOOL_STARTED)")
            uow.insert_row(
                "agent_tool_calls", {"tool_call_id": tool_call_id},
                {"tool_call_id": tool_call_id, "run_id": run_id, "agent_id": agent_id, "tool_name": tool_name, "decision": "ALLOW", "decision_reason": decision_reason, "arguments_hash": arguments_hash, "result_hash": result_hash, "started_at": started_at, "completed_at": completed_at},
            )
            self._append_event(uow, control, f"TOOL_{terminal_state.upper()}", {"tool_call_id": tool_call_id, "completed_at": completed_at, "result_hash": result_hash}, checkpoint=f"tool_{terminal_state}:{tool_name}")
            uow.save_control(run_id, control)
            return tool_call_id

    def record_tool_lifecycle(self, run_id: str, *, agent_id: str, tool_name: str, decision: str, decision_reason: str, arguments_hash: str, result_hash: str | None, started_at: str, completed_at: str | None, terminal_state: str) -> str:
        """Compatibility wrapper: prepare, then (for ALLOW) finish. Prefer the explicit
        prepare_tool_call / finish_tool_call split so the executor runs between them."""
        prep = self.prepare_tool_call(run_id, agent_id=agent_id, tool_name=tool_name, decision=decision, decision_reason=decision_reason, arguments_hash=arguments_hash, started_at=started_at)
        if prep.decision == "DENY":
            return prep.tool_call_id
        return self.finish_tool_call(run_id, tool_call_id=prep.tool_call_id, agent_id=agent_id, tool_name=tool_name, decision_reason=decision_reason, arguments_hash=arguments_hash, result_hash=result_hash, started_at=started_at, completed_at=completed_at, terminal_state=terminal_state)

    # ---- review / score bound to the PERSISTED artifact -------------------
    def _persisted_artifact(self, uow: _UnitOfWork, artifact_id: str) -> dict[str, Any]:
        row = uow.get_row("agent_artifacts", {"artifact_id": artifact_id})
        if row is None or row.get("artifact_type") == RUN_EVENT_TYPE:
            raise PersistenceError(f"artifact not found: {artifact_id}")
        return row

    def record_review(self, review: Review) -> str:
        review.validate()
        _no_secret({"findings": list(review.findings)})
        with self._work() as uow:
            artifact = self._persisted_artifact(uow, review.artifact_id)
            run_id = artifact["run_id"]
            producer = artifact["producer_agent_id"]
            if producer == review.reviewer_agent_id:
                raise PersistenceError("self-review is prohibited (persisted producer == reviewer)")
            if review.artifact_hash != artifact["payload_hash"]:
                raise PersistenceError("review artifact_hash does not match the persisted artifact")
            control = self._require_run(uow, run_id, lock=True)
            existing = uow.get_row("agent_reviews", {"review_id": review.review_id})
            if existing is not None:
                if existing.get("verdict") != review.verdict.value or existing.get("reviewer_agent_id") != review.reviewer_agent_id:
                    raise IdempotencyConflictError(f"review {review.review_id} exists with different evidence")
                return review.review_id
            uow.insert_row(
                "agent_reviews", {"review_id": review.review_id},
                {"review_id": review.review_id, "run_id": run_id, "artifact_id": review.artifact_id, "producer_agent_id": producer, "reviewer_agent_id": review.reviewer_agent_id, "verdict": review.verdict.value, "findings": list(review.findings), "artifact_hash": artifact["payload_hash"], "created_at": self._clock()},
            )
            self._append_event(uow, control, "REVIEW_RECORDED", {"review_id": review.review_id, "artifact_id": review.artifact_id, "verdict": review.verdict.value, "reviewer_agent_id": review.reviewer_agent_id})
            uow.save_control(run_id, control)
            return review.review_id

    def record_score(self, score: Score) -> str:
        score.validate()
        with self._work() as uow:
            artifact = self._persisted_artifact(uow, score.artifact_id)
            run_id = artifact["run_id"]
            producer = artifact["producer_agent_id"]
            if producer == score.scorer_agent_id:
                raise PersistenceError("self-score is prohibited (persisted producer == scorer)")
            control = self._require_run(uow, run_id, lock=True)  # post-run scoring allowed on terminal runs
            existing = uow.get_row("agent_scores", {"score_id": score.score_id})
            if existing is not None:
                if existing.get("scorer_agent_id") != score.scorer_agent_id or existing.get("dimensions") != {k: float(v) for k, v in score.dimensions.items()}:
                    raise IdempotencyConflictError(f"score {score.score_id} exists with different evidence")
                return score.score_id
            uow.insert_row(
                "agent_scores", {"score_id": score.score_id},
                {"score_id": score.score_id, "run_id": run_id, "artifact_id": score.artifact_id, "producer_agent_id": producer, "scorer_agent_id": score.scorer_agent_id, "dimensions": {k: float(v) for k, v in score.dimensions.items()}, "outcome_ref": score.outcome_ref, "created_at": self._clock()},
            )
            self._append_event(uow, control, "SCORE_RECORDED", {"score_id": score.score_id, "artifact_id": score.artifact_id, "scorer_agent_id": score.scorer_agent_id})
            uow.save_control(run_id, control)
            return score.score_id

    # ---- terminal transitions --------------------------------------------
    def _terminate(self, run_id: str, status: str, event_type: str, payload: Mapping[str, Any], *, require_artifact_and_review: bool = False) -> RunState:
        with self._work() as uow:
            control = self._require_open_exec(uow, run_id)
            if require_artifact_and_review:
                materials = [r for r in uow.rows_for_run("agent_artifacts", run_id) if r.get("artifact_type") != RUN_EVENT_TYPE]
                if not materials:
                    raise PersistenceError("completion requires at least one material artifact")
                reviewed = {r["artifact_id"] for r in uow.rows_for_run("agent_reviews", run_id)}
                if not any(m["artifact_id"] in reviewed for m in materials):
                    raise PersistenceError("completion requires at least one independent review of a material artifact")
            self._append_event(uow, control, event_type, {**payload, "status": status}, status=status, checkpoint=status.lower())
            control["completed_at"] = self._clock()
            if status == RunStatus.CANCELLED.value:
                control["cancellation_reason"] = payload.get("reason")
            if "failure_code" in payload:
                control["failure_code"] = payload.get("failure_code")
            uow.save_control(run_id, control)
            return self._state(uow, control)

    def complete_run(self, run_id: str) -> RunState:
        return self._terminate(run_id, RunStatus.COMPLETED.value, "RUN_COMPLETED", {}, require_artifact_and_review=True)

    def fail_run(self, run_id: str, reason: str, failure_code: str = "RUNTIME_FAILURE") -> RunState:
        return self._terminate(run_id, RunStatus.FAILED.value, "RUN_FAILED", {"reason": reason, "failure_code": failure_code})

    def cancel_run(self, run_id: str, reason: str) -> RunState:
        return self._terminate(run_id, RunStatus.CANCELLED.value, "RUN_CANCELLED", {"reason": reason})

    # ---- retrieval / model / deadline / resume lifecycle ------------------
    def record_retrieval_started(self, run_id: str, *, query_hash: str) -> RunState:
        with self._work() as uow:
            control = self._require_open_exec(uow, run_id)
            self._append_event(uow, control, "RETRIEVAL_STARTED", {"query_hash": query_hash, "status": RunStatus.RETRIEVING.value}, status=RunStatus.RETRIEVING.value, checkpoint="retrieval_started")
            uow.save_control(run_id, control)
            return self._state(uow, control)

    def record_retrieval_completed(self, run_id: str, *, refs: Sequence[str], retrieval_hash: str) -> RunState:
        new_refs = [str(r) for r in refs]
        with self._work() as uow:
            control = self._require_open_exec(uow, run_id)
            merged = list(dict.fromkeys(list(control.get("retrieval_refs") or []) + new_refs))
            control["retrieval_refs"] = merged
            control["retrieval_count"] = len(merged)
            self._append_event(uow, control, "RETRIEVAL_COMPLETED", {"retrieval_count": len(merged), "retrieval_hash": retrieval_hash, "status": RunStatus.READY_TO_REASON.value}, status=RunStatus.READY_TO_REASON.value, checkpoint="retrieval_complete")
            uow.save_control(run_id, control)
            return self._state(uow, control)

    def record_model_started(self, run_id: str, *, prompt_version: str, provider_family: str, model: str, request_hash: str, cost_usd: float = 0.0) -> RunState:
        if cost_usd < 0:
            raise PersistenceError("cost_usd must be non-negative")
        with self._work() as uow:
            control = self._require_open_exec(uow, run_id)
            self._bump(control, "model_calls")
            self._bump(control, "cost_usd", float(cost_usd))
            self._append_event(uow, control, "MODEL_STARTED", {"prompt_version": prompt_version, "provider_family": provider_family, "model": model, "request_hash": request_hash, "model_calls": int(control["model_calls"]), "cost_usd": float(control["cost_usd"]), "status": RunStatus.REASONING.value}, status=RunStatus.REASONING.value, checkpoint="model_started")
            uow.save_control(run_id, control)
            return self._state(uow, control)

    def record_model_completed(self, run_id: str, *, output_hash: str) -> RunState:
        with self._work() as uow:
            control = self._require_open_exec(uow, run_id)
            self._append_event(uow, control, "MODEL_COMPLETED", {"output_hash": output_hash, "status": RunStatus.REVIEW_REQUIRED.value}, status=RunStatus.REVIEW_REQUIRED.value, checkpoint="model_complete")
            uow.save_control(run_id, control)
            return self._state(uow, control)

    def record_deadline_exceeded(self, run_id: str, *, deadline_seconds: int, elapsed_seconds: float) -> RunState:
        return self._terminate(run_id, RunStatus.FAILED.value, "RUN_FAILED", {"reason": "agent runtime deadline exceeded", "failure_code": "DEADLINE_EXCEEDED", "deadline_seconds": deadline_seconds, "elapsed_seconds": elapsed_seconds})

    def resume_run(self, run_id: str) -> RunState:
        with self._work() as uow:
            control = self._require_run(uow, run_id, lock=True)
            status = control.get("status")
            if status in (RunStatus.CANCELLED.value, RunStatus.FAILED.value):
                raise TerminalRunError(f"{status} run requires a new immutable envelope")
            if status == RunStatus.COMPLETED.value:
                return self._state(uow, control)  # completed runs never resume
            self._append_event(uow, control, "RUN_RESUMED", {"resume_from": control.get("checkpoint_label"), "status": status})
            uow.save_control(run_id, control)
            return self._state(uow, control)

    # ---- knowledge base (append-only, governed) --------------------------
    def record_lesson(self, *, lesson_id: str, lesson_version: int, lifecycle: str, title: str, statement: str, provenance: Mapping[str, Any], created_by: str, reviewed_by: str | None = None, counterevidence_refs: Sequence[str] = (), valid_from: str | None = None, valid_to: str | None = None) -> str:
        if lesson_version <= 0:
            raise PersistenceError("lesson_version must be positive")
        if lifecycle not in {"CANDIDATE", "RATIFIED", "DISPUTED", "RETIRED"}:
            raise PersistenceError(f"unsupported lesson lifecycle: {lifecycle}")
        if lifecycle == "RATIFIED" and (reviewed_by is None or reviewed_by == created_by):
            raise PersistenceError("ratified lessons require an independent reviewer (no self-ratification)")
        _no_secret({"provenance": dict(provenance), "statement": statement})
        key = (lesson_id, int(lesson_version))
        with self._work() as uow:
            existing = uow.get_row("kb_lessons", {"lesson_id": lesson_id, "lesson_version": int(lesson_version)})
            if existing is not None:
                if existing.get("statement") != statement or existing.get("lifecycle") != lifecycle:
                    raise IdempotencyConflictError(f"lesson {key} exists with different content")
                return f"{lesson_id}:{lesson_version}"
            uow.insert_row(
                "kb_lessons", {"lesson_id": lesson_id, "lesson_version": int(lesson_version)},
                {"lesson_key": f"{lesson_id}:{lesson_version}", "lesson_id": lesson_id, "lesson_version": int(lesson_version), "lifecycle": lifecycle, "title": title, "statement": statement, "provenance": dict(provenance), "counterevidence_refs": list(counterevidence_refs), "valid_from": valid_from or self._clock(), "valid_to": valid_to, "created_by": created_by, "reviewed_by": reviewed_by, "created_at": self._clock()},
            )
            return f"{lesson_id}:{lesson_version}"

    def record_case(self, *, case_id: str, case_type: str, source_refs: Sequence[str], facts: Mapping[str, Any], decision_artifact_id: str | None = None, outcome: Mapping[str, Any] | None = None, outcome_observed_at: str | None = None) -> str:
        _no_secret({"facts": dict(facts), "outcome": dict(outcome or {})})
        with self._work() as uow:
            if decision_artifact_id is not None:
                self._persisted_artifact(uow, decision_artifact_id)  # must reference a persisted artifact
            existing = uow.get_row("kb_cases", {"case_id": case_id})
            if existing is not None:
                if existing.get("facts") != dict(facts):
                    raise IdempotencyConflictError(f"case {case_id} exists with different facts")
                return case_id
            uow.insert_row(
                "kb_cases", {"case_id": case_id},
                {"case_id": case_id, "case_type": case_type, "source_refs": list(source_refs), "facts": dict(facts), "decision_artifact_id": decision_artifact_id, "outcome": dict(outcome) if outcome else None, "outcome_observed_at": outcome_observed_at, "created_at": self._clock()},
            )
            return case_id

    def record_chunk(self, *, chunk_id: str, source_type: str, source_ref: str, source_hash: str, content: str, metadata: Mapping[str, Any] | None = None, embedding_provider: str | None = None, embedding_model: str | None = None, embedding_version: str | None = None, embedding_vector_ref: str | None = None, valid_from: str | None = None, valid_to: str | None = None) -> str:
        if not _HEX64.match(source_hash):
            raise PersistenceError("chunk source_hash must be sha256")
        embed = (embedding_provider, embedding_model, embedding_version)
        if any(embed) and not all(embed):
            raise PersistenceError("embedding provenance requires provider, model and version together")
        _no_secret({"metadata": dict(metadata or {})})
        with self._work() as uow:
            existing = uow.get_row("kb_chunks", {"chunk_id": chunk_id})
            if existing is not None:
                if existing.get("source_hash") != source_hash:
                    raise IdempotencyConflictError(f"chunk {chunk_id} exists with different source_hash")
                return chunk_id
            uow.insert_row(
                "kb_chunks", {"chunk_id": chunk_id},
                {"chunk_id": chunk_id, "source_type": source_type, "source_ref": source_ref, "source_hash": source_hash, "content": content, "metadata": dict(metadata or {}), "embedding_provider": embedding_provider, "embedding_model": embedding_model, "embedding_version": embedding_version, "embedding_vector_ref": embedding_vector_ref, "valid_from": valid_from or self._clock(), "valid_to": valid_to, "created_at": self._clock()},
            )
            return chunk_id

    # ---- reads ------------------------------------------------------------
    def reconstruct(self, run_id: str) -> RunState:
        with self._work() as uow:
            control = self._require_run(uow, run_id, lock=False)
            self._load_events(uow, run_id)
            return self._state(uow, control)

    def journal(self, run_id: str) -> list[JournalEvent]:
        with self._work() as uow:
            self._require_run(uow, run_id, lock=False)
            out: list[JournalEvent] = []
            for row in self._load_events(uow, run_id):
                body = row["payload"]
                out.append(JournalEvent(run_id=run_id, sequence=int(body["sequence"]), event_type=body["event_type"], payload=body["payload"], created_at=body["created_at"], previous_hash=body["previous_hash"], event_hash=row["payload_hash"]))
            return out


# --------------------------------------------------------------------------- #
# In-memory backend — copy-on-write unit of work for true rollback.
# --------------------------------------------------------------------------- #
_PK = {
    "agent_artifacts": "artifact_id", "agent_tool_calls": "tool_call_id", "agent_reviews": "review_id",
    "agent_scores": "score_id", "kb_lessons": "lesson_key", "kb_cases": "case_id", "kb_chunks": "chunk_id",
}


class _MemoryStore:
    def __init__(self) -> None:
        self.control: dict[str, dict[str, Any]] = {}
        self.tables: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in _PK}
        self.run_lock = threading.Lock()
        self.locks: dict[str, threading.Lock] = {}


class _MemoryUnit(_UnitOfWork):
    def __init__(self, store: _MemoryStore) -> None:
        self._store = store
        self._control = copy.deepcopy(store.control)
        self._tables = copy.deepcopy(store.tables)
        self._held: list[threading.Lock] = []

    def load_control(self, run_id, *, lock):
        if lock:
            with self._store.run_lock:
                run_lock = self._store.locks.setdefault(run_id, threading.Lock())
            run_lock.acquire()
            self._held.append(run_lock)
        row = self._control.get(run_id)
        return copy.deepcopy(row) if row is not None else None

    def insert_control(self, row):
        self._control[row["run_id"]] = copy.deepcopy(dict(row))
        return True

    def save_control(self, run_id, row):
        self._control[run_id] = copy.deepcopy(dict(row))

    def insert_row(self, table, conflict_key, row):
        store = self._tables[table]
        if any(all(existing.get(k) == v for k, v in conflict_key.items()) for existing in store.values()):
            return False
        store[row[_PK[table]]] = copy.deepcopy(dict(row))
        return True

    def get_row(self, table, key):
        for row in self._tables[table].values():
            if all(row.get(k) == v for k, v in key.items()):
                return copy.deepcopy(row)
        return None

    def rows_for_run(self, table, run_id):
        return [copy.deepcopy(r) for r in self._tables[table].values() if r.get("run_id") == run_id]

    def commit(self):
        self._store.control = self._control
        self._store.tables = self._tables
        self._release()

    def rollback(self):
        self._release()

    def close(self):
        self._release()

    def _release(self):
        while self._held:
            self._held.pop().release()


class InMemoryPersistence(_PersistenceBase):
    """Hermetic reference backend. Transactional via copy-on-write; thread-safe."""

    def __init__(self, *, clock=utc_now) -> None:
        super().__init__(clock=clock)
        self._store = _MemoryStore()

    def _unit(self) -> _UnitOfWork:
        return _MemoryUnit(self._store)


# --------------------------------------------------------------------------- #
# Postgres backend — one connection + one transaction per operation.
# --------------------------------------------------------------------------- #
_APPEND_COLUMNS: dict[str, tuple[str, ...]] = {
    "agent_artifacts": ("artifact_id", "run_id", "producer_agent_id", "artifact_type", "payload", "payload_hash", "input_hash", "validation_hash", "retrieval_refs", "prompt_version", "provider_family", "model", "created_at"),
    "agent_tool_calls": ("tool_call_id", "run_id", "agent_id", "tool_name", "decision", "decision_reason", "arguments_hash", "result_hash", "started_at", "completed_at"),
    "agent_reviews": ("review_id", "artifact_id", "producer_agent_id", "reviewer_agent_id", "verdict", "findings", "artifact_hash", "created_at"),
    "agent_scores": ("score_id", "artifact_id", "producer_agent_id", "scorer_agent_id", "dimensions", "outcome_ref", "created_at"),
    "kb_lessons": ("lesson_id", "lesson_version", "lifecycle", "title", "statement", "provenance", "counterevidence_refs", "valid_from", "valid_to", "created_by", "reviewed_by", "created_at"),
    "kb_cases": ("case_id", "case_type", "source_refs", "facts", "decision_artifact_id", "outcome", "outcome_observed_at", "created_at"),
    "kb_chunks": ("chunk_id", "source_type", "source_ref", "source_hash", "content", "metadata", "embedding_provider", "embedding_model", "embedding_version", "embedding_vector_ref", "valid_from", "valid_to", "created_at"),
}
_JSONB_COLUMNS = frozenset({"payload", "retrieval_refs", "findings", "dimensions", "budget", "checkpoint", "provenance", "counterevidence_refs", "source_refs", "facts", "outcome", "metadata"})
_CONFLICT = {"agent_artifacts": "(run_id, payload_hash)", "agent_tool_calls": "(tool_call_id)", "agent_reviews": "(review_id)", "agent_scores": "(score_id)", "kb_lessons": "(lesson_id, lesson_version)", "kb_cases": "(case_id)", "kb_chunks": "(chunk_id)"}
_KEY_COLUMNS = {"agent_artifacts": ("artifact_id", "run_id", "payload_hash"), "agent_tool_calls": ("tool_call_id",), "agent_reviews": ("review_id",), "agent_scores": ("score_id",), "kb_lessons": ("lesson_id", "lesson_version"), "kb_cases": ("case_id",), "kb_chunks": ("chunk_id",)}
_RUN_COLS = ("run_id", "agent_id", "agent_version", "job_type", "environment", "objective", "status", "input_hash", "validation_hash", "retrieval_count", "model_calls", "tool_calls", "cost_usd", "checkpoint_seq", "checkpoint", "budget", "cancellation_reason", "started_at", "updated_at", "completed_at")
_CHILD_RUN_JOIN = {"agent_reviews", "agent_scores"}


def _iso(value: Any) -> Any:
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value


class _PostgresUnit(_UnitOfWork):
    def __init__(self, connection: Any, schema: str, timeout_ms: int) -> None:
        self._c = connection
        self._schema = schema
        cur = self._c.cursor()
        cur.execute("SET LOCAL statement_timeout = %s", (timeout_ms,))
        cur.close()

    def _q(self, table: str) -> str:
        return f"{self._schema}.{table}"

    def _param(self, column: str, value: Any) -> Any:
        return canonical_json(value) if column in _JSONB_COLUMNS else value

    def _cursor(self, sql: str, params: Sequence[Any] = ()):
        cur = self._c.cursor()
        cur.execute(sql, tuple(params))
        return cur

    def load_control(self, run_id, *, lock):
        cur = self._cursor(f"SELECT {', '.join(_RUN_COLS)} FROM {self._q('agent_runs')} WHERE run_id=%s{' FOR UPDATE' if lock else ''}", (run_id,))
        row = cur.fetchone()
        cur.close()
        if row is None:
            return None
        data = dict(zip(_RUN_COLS, row))
        checkpoint = data.get("checkpoint") if isinstance(data.get("checkpoint"), Mapping) else {}
        budget = data.get("budget") if isinstance(data.get("budget"), Mapping) else {}
        return {
            "run_id": data["run_id"], "agent_id": data["agent_id"], "agent_version": data["agent_version"],
            "job_type": data["job_type"], "environment": data["environment"], "objective": data["objective"],
            "objective_hash": checkpoint.get("objective_hash", canonical_hash(data["objective"])),
            "status": data["status"], "input_hash": data["input_hash"], "validation_hash": data["validation_hash"],
            "retrieval_count": data["retrieval_count"], "model_calls": data["model_calls"], "tool_calls": data["tool_calls"],
            "cost_usd": float(data["cost_usd"]), "checkpoint_seq": data["checkpoint_seq"],
            "head_hash": checkpoint.get("head_hash", GENESIS_HASH), "checkpoint_label": checkpoint.get("checkpoint_label"),
            "budget": dict(budget), "cancellation_reason": data["cancellation_reason"],
            "started_at": _iso(data["started_at"]), "updated_at": _iso(data["updated_at"]), "completed_at": _iso(data["completed_at"]),
            # exact envelope timestamp (authoritative deadline origin), cumulative refs and failure code
            # survive round-trips through the checkpoint JSON projection with deterministic safe defaults.
            "created_at": checkpoint.get("created_at"),
            "retrieval_refs": [str(ref) for ref in (checkpoint.get("retrieval_refs") or [])],
            "failure_code": checkpoint.get("failure_code"),
        }

    def _checkpoint(self, control: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "head_hash": control.get("head_hash", GENESIS_HASH),
            "checkpoint_label": control.get("checkpoint_label"),
            "objective_hash": control.get("objective_hash"),
            "created_at": control.get("created_at"),
            "retrieval_refs": [str(ref) for ref in (control.get("retrieval_refs") or [])],
            "failure_code": control.get("failure_code"),
        }

    def insert_control(self, row):
        cur = self._cursor(
            f"INSERT INTO {self._q('agent_runs')} (run_id, agent_id, agent_version, job_type, environment, objective, status, input_hash, validation_hash, retrieval_count, model_calls, tool_calls, cost_usd, checkpoint_seq, checkpoint, budget, started_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s) ON CONFLICT (run_id) DO NOTHING",
            (row["run_id"], row["agent_id"], row["agent_version"], row["job_type"], row["environment"], row["objective"], row["status"], row["input_hash"], row["validation_hash"], row.get("retrieval_count", 0), row.get("model_calls", 0), row.get("tool_calls", 0), row.get("cost_usd", 0.0), row.get("checkpoint_seq", 0), self._param("checkpoint", self._checkpoint(row)), self._param("budget", row.get("budget", {})), row["started_at"], row.get("updated_at", row["started_at"])),
        )
        inserted = cur.rowcount == 1
        cur.close()
        return inserted

    def save_control(self, run_id, row):
        cur = self._cursor(
            f"UPDATE {self._q('agent_runs')} SET status=%s, retrieval_count=%s, model_calls=%s, tool_calls=%s, cost_usd=%s, checkpoint_seq=%s, checkpoint=%s::jsonb, updated_at=%s, completed_at=%s, cancellation_reason=%s WHERE run_id=%s",
            (row.get("status"), row.get("retrieval_count", 0), row.get("model_calls", 0), row.get("tool_calls", 0), row.get("cost_usd", 0.0), row.get("checkpoint_seq", 0), self._param("checkpoint", self._checkpoint(row)), row.get("updated_at"), row.get("completed_at"), row.get("cancellation_reason"), run_id),
        )
        cur.close()

    def insert_row(self, table, conflict_key, row):
        cols = _APPEND_COLUMNS[table]
        placeholders = ", ".join("%s::jsonb" if c in _JSONB_COLUMNS else "%s" for c in cols)
        cur = self._cursor(f"INSERT INTO {self._q(table)} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT {_CONFLICT[table]} DO NOTHING", [self._param(c, row.get(c)) for c in cols])
        inserted = cur.rowcount == 1
        cur.close()
        return inserted

    def get_row(self, table, key):
        cols = _APPEND_COLUMNS[table]
        where = " AND ".join(f"{k}=%s" for k in key)
        cur = self._cursor(f"SELECT {', '.join(cols)} FROM {self._q(table)} WHERE {where}", tuple(key.values()))
        row = cur.fetchone()
        cur.close()
        if row is None:
            return None
        out = {c: (_iso(v)) for c, v in zip(cols, row)}
        out["run_id"] = out.get("run_id") or self._row_run(table, out)
        return out

    def _row_run(self, table, out):
        if "run_id" in _APPEND_COLUMNS[table]:
            return out.get("run_id")
        return None

    def rows_for_run(self, table, run_id):
        cols = _APPEND_COLUMNS[table]
        if table in _CHILD_RUN_JOIN:
            cur = self._cursor(f"SELECT {', '.join('c.'+c for c in cols)} FROM {self._q(table)} c JOIN {self._q('agent_artifacts')} a ON a.artifact_id=c.artifact_id WHERE a.run_id=%s", (run_id,))
        elif "run_id" in cols:
            cur = self._cursor(f"SELECT {', '.join(cols)} FROM {self._q(table)} WHERE run_id=%s", (run_id,))
        else:
            return []
        rows = cur.fetchall()
        cur.close()
        result = []
        for r in rows:
            d = {c: _iso(v) for c, v in zip(cols, r)}
            if "run_id" not in d:
                d["run_id"] = run_id
            result.append(d)
        return result

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        pass


class PostgresPersistence(_PersistenceBase):
    """Authoritative eight-table backend. One connection + one transaction per op.

    ``connection_factory`` is a zero-arg callable returning a fresh DB-API 2.0
    connection (autocommit off) whose role is an approved LAB/SHADOW runtime writer.
    Runtime identity is verified automatically before the first write.
    """

    schema = "agentic_runtime"

    def __init__(self, connection_factory, *, clock=utc_now, statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS, role_allowlist: Sequence[str] = DEFAULT_RUNTIME_ROLE_ALLOWLIST, verify_identity: bool = True) -> None:
        super().__init__(clock=clock)
        if not callable(connection_factory):
            raise PersistenceError("connection_factory must be a zero-arg callable returning a fresh connection")
        self._factory = connection_factory
        self._timeout_ms = int(statement_timeout_ms)
        self._allowlist = tuple(role_allowlist)
        self._verify = verify_identity
        self._verified = False

    def _unit(self) -> _UnitOfWork:
        if self._verify and not self._verified:
            self._run_identity_check()
            self._verified = True
        return _PostgresUnit(self._factory(), self.schema, self._timeout_ms)

    def _run_identity_check(self) -> None:
        # Automatic, on a dedicated short-lived connection closed before any write.
        conn = self._factory()
        try:
            self._verify_identity(conn)
        finally:
            closer = getattr(conn, "close", None)
            if callable(closer):
                conn.close()

    def _verify_identity(self, conn: Any) -> None:
        cur = conn.cursor()
        cur.execute("SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        row = cur.fetchone()
        cur.close()
        if row is None:
            raise RuntimeIdentityError("runtime role is not present in pg_roles")
        user, is_super, createdb, createrole, replication, bypassrls = row
        if user not in self._allowlist:
            raise RuntimeIdentityError(f"runtime writer {user!r} is not in the approved allowlist")
        if any((is_super, createdb, createrole, replication, bypassrls)):
            raise RuntimeIdentityError("runtime writer must not hold superuser/createdb/createrole/replication/bypassrls")
