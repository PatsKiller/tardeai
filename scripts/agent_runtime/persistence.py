"""Persistence protocol and backends for the governed agent runtime (MVL).

This module defines one explicit persistence protocol and two backends that share
*identical* semantics through a template-method base:

* ``InMemoryPersistence`` — hermetic reference backend for deterministic tests and
  shadow replay; no external dependency.
* ``PostgresPersistence`` — the authoritative backend for the eight-table
  ``agentic_runtime`` schema. It never imports a database driver: the caller injects
  a DB-API 2.0 connection whose runtime credential may reach only ``agentic_runtime``.
  The migration identity is never required here.

Design invariants (all enforced in the shared base so both backends agree):

* Runs are the single mutable control row; artifacts, tool calls, reviews, scores,
  lessons, cases and chunks are append-only, matching the migration triggers.
* Every append advances a per-run monotonic ``sequence`` and a SHA-256 hash chain
  serialized by a per-run write lock (``SELECT ... FOR UPDATE`` on Postgres), so the
  chain cannot silently fork under concurrency.
* Idempotency is keyed by stable run / artifact / tool-call / review / score identity
  (deterministic ids and the ``UNIQUE (run_id, payload_hash)`` artifact key), never a
  random UUID with an ineffective ``ON CONFLICT``.
* Producer/reviewer and producer/scorer separation is enforced in application logic
  in addition to the database ``CHECK`` constraints. There is no self-review or
  self-score path.
* No raw secret, token, DSN, environment dump, or arbitrary provider payload is
  persisted: every payload passes ``assert_no_secret_material`` first.
* Terminal runs (COMPLETED / CANCELLED / FAILED) never mutate again and never resume;
  a new run requires a new immutable envelope.
* A failed persistence step raises and rolls back; it is never returned as a
  completed checkpoint or a successful artifact.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
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

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL = frozenset({RunStatus.COMPLETED.value, RunStatus.CANCELLED.value, RunStatus.FAILED.value})


class PersistenceError(RuntimeError):
    """Raised when a persistence invariant is violated or a write fails."""


class TerminalRunError(PersistenceError):
    """Raised when a terminal run is mutated or resumed."""


@dataclass(frozen=True)
class JournalEvent:
    """One hash-chained run event. Byte-compatible with journal.RunEvent."""

    run_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    created_at: str
    previous_hash: str
    event_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True)
class RunState:
    """Deterministic reconstruction of a run from persisted evidence alone."""

    run_id: str
    status: str
    sequence: int
    head_hash: str
    checkpoint: str | None
    artifacts: tuple[str, ...]
    tool_calls: tuple[str, ...]
    reviews: tuple[str, ...]
    scores: tuple[str, ...]
    updated_at: str | None


def event_body(run_id: str, sequence: int, event_type: str, payload: Mapping[str, Any], created_at: str, previous_hash: str) -> dict[str, Any]:
    """The exact pre-image hashed for a journal event (same as the in-memory journal)."""

    return {
        "run_id": run_id,
        "sequence": sequence,
        "event_type": event_type,
        "payload": dict(payload),
        "created_at": created_at,
        "previous_hash": previous_hash,
    }


def compute_event_hash(body: Mapping[str, Any]) -> str:
    return canonical_hash(body)


def derive_id(*parts: object) -> str:
    """Deterministic 64-hex identity from stable parts. Same inputs -> same id.

    Used for tool-call / review / score identity so a duplicate submission is a
    no-op instead of a second row, without relying on a random UUID.
    """

    return canonical_hash(["agentic_runtime.id", *[str(part) for part in parts]])


@runtime_checkable
class RunPersistence(Protocol):
    """Explicit persistence protocol shared by every backend and the orchestrator."""

    def create_run(self, envelope: RunEnvelope, budget: BudgetPolicy) -> RunState: ...
    def record_artifact(self, artifact: Artifact, *, retrieval_required: bool = True) -> str: ...
    def record_tool_call(
        self,
        run_id: str,
        *,
        agent_id: str,
        tool_name: str,
        decision: str,
        decision_reason: str,
        arguments_hash: str,
        result_hash: str | None,
        started_at: str,
        completed_at: str | None,
        terminal_state: str,
    ) -> str: ...
    def record_review(self, run_id: str, review: Review) -> str: ...
    def record_score(self, run_id: str, score: Score) -> str: ...
    def complete_run(self, run_id: str) -> RunState: ...
    def fail_run(self, run_id: str, reason: str, failure_code: str = "RUNTIME_FAILURE") -> RunState: ...
    def cancel_run(self, run_id: str, reason: str) -> RunState: ...
    def reconstruct(self, run_id: str) -> RunState: ...
    def journal(self, run_id: str) -> list[JournalEvent]: ...


class _PersistenceBase:
    """Template-method base: all semantics live here so backends stay identical.

    Subclasses implement only the storage primitives (``_txn``, ``_load_control``,
    ``_save_control``, ``_insert_*`` and the read helpers). The base owns validation,
    the hash chain, idempotency, self-review/score denial and terminal enforcement.
    """

    def __init__(self, *, clock=utc_now) -> None:
        self._clock = clock

    # ---- storage primitives implemented by each backend -------------------
    @contextmanager
    def _txn(self, run_id: str | None = None) -> Iterator[None]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _load_control(self, run_id: str) -> dict[str, Any] | None:  # pragma: no cover
        raise NotImplementedError

    def _insert_control(self, row: Mapping[str, Any]) -> bool:  # pragma: no cover
        raise NotImplementedError

    def _save_control(self, run_id: str, updates: Mapping[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError

    def _insert_append_only(self, table: str, key: Mapping[str, Any], row: Mapping[str, Any]) -> bool:  # pragma: no cover
        raise NotImplementedError

    def _child_ids(self, table: str, run_id: str) -> tuple[str, ...]:  # pragma: no cover
        raise NotImplementedError

    def _artifact_run(self, artifact_id: str) -> str | None:  # pragma: no cover
        raise NotImplementedError

    # ---- shared journal / control logic -----------------------------------
    def _append_locked(self, control: dict[str, Any], event_type: str, payload: Mapping[str, Any], *, status: str | None = None, checkpoint: str | None = None) -> JournalEvent:
        assert_no_secret_material(payload)
        events: list[dict[str, Any]] = list(control.get("events") or [])
        if len(events) >= MAX_JOURNAL_EVENTS:
            raise PersistenceError("run journal exceeds bounded event budget")
        sequence = len(events) + 1
        previous_hash = events[-1]["event_hash"] if events else GENESIS_HASH
        created_at = self._clock()
        body = event_body(control["run_id"], sequence, event_type, payload, created_at, previous_hash)
        event_hash = compute_event_hash(body)
        event = JournalEvent(**body, event_hash=event_hash)
        events.append(event.as_dict())
        control["events"] = events
        control["checkpoint_seq"] = sequence
        control["head_hash"] = event_hash
        control["updated_at"] = created_at
        if checkpoint is not None:
            control["checkpoint_label"] = checkpoint
        if status is not None:
            control["status"] = status
        return event

    def _require_open(self, control: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
        if control is None:
            raise PersistenceError(f"unknown run: {run_id}")
        if control.get("status") in _TERMINAL:
            raise TerminalRunError(f"run is terminal: {control.get('status')}")
        return control

    def _state(self, control: dict[str, Any]) -> RunState:
        run_id = control["run_id"]
        return RunState(
            run_id=run_id,
            status=control.get("status", RunStatus.CREATED.value),
            sequence=int(control.get("checkpoint_seq", 0)),
            head_hash=control.get("head_hash", GENESIS_HASH),
            checkpoint=control.get("checkpoint_label"),
            artifacts=self._child_ids("agent_artifacts", run_id),
            tool_calls=self._child_ids("agent_tool_calls", run_id),
            reviews=self._child_ids("agent_reviews", run_id),
            scores=self._child_ids("agent_scores", run_id),
            updated_at=control.get("updated_at"),
        )

    # ---- public protocol --------------------------------------------------
    def create_run(self, envelope: RunEnvelope, budget: BudgetPolicy) -> RunState:
        budget.validate()
        if envelope.environment not in {Environment.LAB, Environment.SHADOW}:
            raise PersistenceError("MVL persistence is LAB/SHADOW only")
        if not _HEX64.match(envelope.input_hash) or not _HEX64.match(envelope.validation_hash):
            raise PersistenceError("run hashes must be sha256")
        with self._txn(envelope.run_id):
            existing = self._load_control(envelope.run_id)
            if existing is not None:
                # Idempotent create: identical envelope is a no-op; a different
                # envelope under the same id is a hard conflict (immutable identity).
                if existing.get("input_hash") != envelope.input_hash or existing.get("validation_hash") != envelope.validation_hash:
                    raise PersistenceError(f"run_id {envelope.run_id} already exists with different envelope")
                return self._state(existing)
            control: dict[str, Any] = {
                "run_id": envelope.run_id,
                "agent_id": envelope.agent_id,
                "agent_version": envelope.agent_version,
                "job_type": envelope.job_type,
                "environment": envelope.environment.value,
                "objective": envelope.objective,
                "status": RunStatus.CREATED.value,
                "input_hash": envelope.input_hash,
                "validation_hash": envelope.validation_hash,
                "budget": {
                    "max_model_calls": budget.max_model_calls,
                    "max_tool_calls": budget.max_tool_calls,
                    "max_cost_usd": budget.max_cost_usd,
                    "deadline_seconds": budget.deadline_seconds,
                },
                "checkpoint_seq": 0,
                "head_hash": GENESIS_HASH,
                "events": [],
                "started_at": self._clock(),
            }
            self._append_locked(control, "RUN_CREATED", {"status": RunStatus.CREATED.value, "objective_hash": canonical_hash(envelope.objective)}, status=RunStatus.CREATED.value, checkpoint="created")
            self._insert_control(control)
            return self._state(control)

    def record_artifact(self, artifact: Artifact, *, retrieval_required: bool = True) -> str:
        artifact.validate(retrieval_required=retrieval_required)
        assert_no_secret_material(dict(artifact.payload))
        with self._txn(artifact.run_id):
            control = self._require_open(self._load_control(artifact.run_id), artifact.run_id)
            # Idempotency is the natural UNIQUE(run_id, payload_hash) key.
            inserted = self._insert_append_only(
                "agent_artifacts",
                {"run_id": artifact.run_id, "payload_hash": artifact.payload_hash},
                {
                    "artifact_id": artifact.artifact_id,
                    "run_id": artifact.run_id,
                    "producer_agent_id": artifact.producer_agent_id,
                    "artifact_type": artifact.artifact_type,
                    "payload": dict(artifact.payload),
                    "payload_hash": artifact.payload_hash,
                    "input_hash": artifact.input_hash,
                    "validation_hash": artifact.validation_hash,
                    "retrieval_refs": list(artifact.retrieval_refs),
                    "prompt_version": artifact.prompt_version,
                    "provider_family": artifact.provider_family,
                    "model": artifact.model,
                    "created_at": self._clock(),
                },
            )
            if inserted:
                self._append_locked(control, "ARTIFACT_CREATED", {"artifact_id": artifact.artifact_id, "payload_hash": artifact.payload_hash, "producer_agent_id": artifact.producer_agent_id}, status=RunStatus.REVIEW_REQUIRED.value, checkpoint="artifact_created")
                self._save_control(artifact.run_id, control)
            return artifact.artifact_id

    def record_tool_call(self, run_id: str, *, agent_id: str, tool_name: str, decision: str, decision_reason: str, arguments_hash: str, result_hash: str | None, started_at: str, completed_at: str | None, terminal_state: str) -> str:
        if decision not in {"ALLOW", "DENY"}:
            raise PersistenceError("tool decision must be ALLOW or DENY")
        if terminal_state not in {"completed", "failed", "cancelled"}:
            raise PersistenceError("tool terminal_state must be completed/failed/cancelled")
        if not _HEX64.match(arguments_hash) or (result_hash is not None and not _HEX64.match(result_hash)):
            raise PersistenceError("tool-call hashes must be sha256")
        # Deterministic identity: same tool call resubmitted is idempotent.
        tool_call_id = derive_id("tool_call", run_id, agent_id, tool_name, arguments_hash, started_at)
        with self._txn(run_id):
            control = self._require_open(self._load_control(run_id), run_id)
            inserted = self._insert_append_only(
                "agent_tool_calls",
                {"tool_call_id": tool_call_id},
                {
                    "tool_call_id": tool_call_id,
                    "run_id": run_id,
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "decision": decision,
                    "decision_reason": decision_reason,
                    "arguments_hash": arguments_hash,
                    "result_hash": result_hash,
                    "started_at": started_at,
                    "completed_at": completed_at,
                },
            )
            if inserted:
                self._append_locked(control, "TOOL_PROPOSED", {"tool_call_id": tool_call_id, "tool_name": tool_name, "decision": decision}, checkpoint=f"tool_proposed:{tool_name}")
                self._append_locked(control, "TOOL_STARTED", {"tool_call_id": tool_call_id, "started_at": started_at}, checkpoint=f"tool_started:{tool_name}")
                self._append_locked(control, f"TOOL_{terminal_state.upper()}", {"tool_call_id": tool_call_id, "completed_at": completed_at, "result_hash": result_hash}, checkpoint=f"tool_{terminal_state}:{tool_name}")
                self._save_control(run_id, control)
            return tool_call_id

    def record_review(self, run_id: str, review: Review) -> str:
        review.validate()
        if review.producer_agent_id == review.reviewer_agent_id:
            raise PersistenceError("self-review is prohibited")
        assert_no_secret_material({"findings": list(review.findings)})
        if self._artifact_run(review.artifact_id) not in (run_id, None) and self._artifact_run(review.artifact_id) is not None:
            if self._artifact_run(review.artifact_id) != run_id:
                raise PersistenceError("review artifact belongs to a different run")
        with self._txn(run_id):
            control = self._require_open(self._load_control(run_id), run_id)
            inserted = self._insert_append_only(
                "agent_reviews",
                {"review_id": review.review_id},
                {
                    "review_id": review.review_id,
                    "run_id": run_id,
                    "artifact_id": review.artifact_id,
                    "producer_agent_id": review.producer_agent_id,
                    "reviewer_agent_id": review.reviewer_agent_id,
                    "verdict": review.verdict.value,
                    "findings": list(review.findings),
                    "artifact_hash": review.artifact_hash,
                    "created_at": self._clock(),
                },
            )
            if inserted:
                self._append_locked(control, "REVIEW_RECORDED", {"review_id": review.review_id, "artifact_id": review.artifact_id, "verdict": review.verdict.value}, checkpoint="review_recorded")
                self._save_control(run_id, control)
            return review.review_id

    def record_score(self, run_id: str, score: Score) -> str:
        score.validate()
        if score.producer_agent_id == score.scorer_agent_id:
            raise PersistenceError("self-score is prohibited")
        with self._txn(run_id):
            control = self._require_open(self._load_control(run_id), run_id)
            inserted = self._insert_append_only(
                "agent_scores",
                {"score_id": score.score_id},
                {
                    "score_id": score.score_id,
                    "run_id": run_id,
                    "artifact_id": score.artifact_id,
                    "producer_agent_id": score.producer_agent_id,
                    "scorer_agent_id": score.scorer_agent_id,
                    "dimensions": {key: float(value) for key, value in score.dimensions.items()},
                    "outcome_ref": score.outcome_ref,
                    "created_at": self._clock(),
                },
            )
            if inserted:
                self._append_locked(control, "SCORE_RECORDED", {"score_id": score.score_id, "artifact_id": score.artifact_id}, checkpoint="score_recorded")
                self._save_control(run_id, control)
            return score.score_id

    def _terminate(self, run_id: str, status: str, event_type: str, payload: Mapping[str, Any]) -> RunState:
        with self._txn(run_id):
            control = self._require_open(self._load_control(run_id), run_id)
            self._append_locked(control, event_type, {**payload, "status": status}, status=status, checkpoint=status.lower())
            control["completed_at"] = self._clock()
            if status == RunStatus.CANCELLED.value:
                control["cancellation_reason"] = payload.get("reason")
            self._save_control(run_id, control)
            return self._state(control)

    def complete_run(self, run_id: str) -> RunState:
        return self._terminate(run_id, RunStatus.COMPLETED.value, "RUN_COMPLETED", {})

    def fail_run(self, run_id: str, reason: str, failure_code: str = "RUNTIME_FAILURE") -> RunState:
        return self._terminate(run_id, RunStatus.FAILED.value, "RUN_FAILED", {"reason": reason, "failure_code": failure_code})

    def cancel_run(self, run_id: str, reason: str) -> RunState:
        return self._terminate(run_id, RunStatus.CANCELLED.value, "RUN_CANCELLED", {"reason": reason})

    def reconstruct(self, run_id: str) -> RunState:
        control = self._load_control(run_id)
        if control is None:
            raise PersistenceError(f"unknown run: {run_id}")
        return self._state(control)

    def journal(self, run_id: str) -> list[JournalEvent]:
        control = self._load_control(run_id)
        if control is None:
            raise PersistenceError(f"unknown run: {run_id}")
        return [JournalEvent(**dict(event)) for event in (control.get("events") or [])]


class InMemoryPersistence(_PersistenceBase):
    """Hermetic reference backend. Thread-safe; used for deterministic tests."""

    def __init__(self, *, clock=utc_now) -> None:
        super().__init__(clock=clock)
        self._control: dict[str, dict[str, Any]] = {}
        self._tables: dict[str, dict[str, dict[str, Any]]] = {
            name: {} for name in ("agent_artifacts", "agent_tool_calls", "agent_reviews", "agent_scores")
        }
        self._unique: dict[str, set[tuple]] = {name: set() for name in self._tables}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    @contextmanager
    def _txn(self, run_id: str | None = None) -> Iterator[None]:
        # Per-run lock serializes appends -> monotonic sequence, non-forking chain.
        if run_id is None:
            yield
            return
        with self._guard:
            lock = self._locks.setdefault(run_id, threading.Lock())
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _load_control(self, run_id: str) -> dict[str, Any] | None:
        row = self._control.get(run_id)
        return dict(row) if row is not None else None

    def _insert_control(self, row: Mapping[str, Any]) -> bool:
        self._control[row["run_id"]] = dict(row)
        return True

    def _save_control(self, run_id: str, updates: Mapping[str, Any]) -> None:
        self._control[run_id] = dict(updates)

    def _insert_append_only(self, table: str, key: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
        unique_key = tuple(sorted(key.items()))
        if unique_key in self._unique[table]:
            return False
        pk = next(iter(row))
        self._unique[table].add(unique_key)
        self._tables[table][row[pk]] = dict(row)
        return True

    def _child_ids(self, table: str, run_id: str) -> tuple[str, ...]:
        rows = [row for row in self._tables[table].values() if row.get("run_id") == run_id]
        rows.sort(key=lambda row: row.get("created_at") or row.get("started_at") or "")
        pk = {
            "agent_artifacts": "artifact_id",
            "agent_tool_calls": "tool_call_id",
            "agent_reviews": "review_id",
            "agent_scores": "score_id",
        }[table]
        return tuple(row[pk] for row in rows)

    def _artifact_run(self, artifact_id: str) -> str | None:
        row = self._tables["agent_artifacts"].get(artifact_id)
        return row.get("run_id") if row else None

    def _reviews_and_scores_run(self, table: str, artifact_id: str) -> None:  # pragma: no cover - helper reserved
        return None


# Column order for each append-only INSERT. Extra keys on the row (e.g. an internal
# run_id carried for reviews/scores) are ignored — only these columns are written.
_APPEND_COLUMNS: dict[str, tuple[str, ...]] = {
    "agent_artifacts": (
        "artifact_id", "run_id", "producer_agent_id", "artifact_type", "payload",
        "payload_hash", "input_hash", "validation_hash", "retrieval_refs",
        "prompt_version", "provider_family", "model", "created_at",
    ),
    "agent_tool_calls": (
        "tool_call_id", "run_id", "agent_id", "tool_name", "decision",
        "decision_reason", "arguments_hash", "result_hash", "started_at", "completed_at",
    ),
    "agent_reviews": (
        "review_id", "artifact_id", "producer_agent_id", "reviewer_agent_id",
        "verdict", "findings", "artifact_hash", "created_at",
    ),
    "agent_scores": (
        "score_id", "artifact_id", "producer_agent_id", "scorer_agent_id",
        "dimensions", "outcome_ref", "created_at",
    ),
}
_JSONB_COLUMNS = frozenset({"payload", "retrieval_refs", "findings", "dimensions", "budget", "checkpoint"})
_CONFLICT_TARGET: dict[str, str] = {
    "agent_artifacts": "(run_id, payload_hash)",
    "agent_tool_calls": "(tool_call_id)",
    "agent_reviews": "(review_id)",
    "agent_scores": "(score_id)",
}
_CHILD_PK: dict[str, str] = {
    "agent_artifacts": "artifact_id",
    "agent_tool_calls": "tool_call_id",
    "agent_reviews": "review_id",
    "agent_scores": "score_id",
}


class PostgresPersistence(_PersistenceBase):
    """Authoritative eight-table backend over an *injected* DB-API 2.0 connection.

    The driver is never imported here; the caller supplies a connection whose runtime
    role may reach only ``agentic_runtime``. Every write runs in an explicit
    transaction with a bounded ``statement_timeout``, parameterized SQL, deterministic
    JSONB serialization, and fail-closed rollback.
    """

    schema = "agentic_runtime"

    def __init__(self, connection: Any, *, clock=utc_now, statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS) -> None:
        super().__init__(clock=clock)
        self._conn = connection
        self._timeout_ms = int(statement_timeout_ms)
        self._locking = False

    # ---- low-level SQL helpers -------------------------------------------
    def _q(self, table: str) -> str:
        return f"{self.schema}.{table}"

    def _param(self, column: str, value: Any) -> Any:
        if column in _JSONB_COLUMNS:
            return canonical_json(value)
        return value

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, tuple(params))
            return cursor
        except Exception:
            cursor.close()
            raise

    @contextmanager
    def _txn(self, run_id: str | None = None) -> Iterator[None]:
        self._locking = run_id is not None
        try:
            cursor = self._conn.cursor()
            cursor.execute("SET LOCAL statement_timeout = %s", (self._timeout_ms,))
            cursor.close()
            yield
            self._conn.commit()
        except PersistenceError:
            self._conn.rollback()
            raise
        except Exception as exc:  # any driver/SQL failure rolls back, never a success
            self._conn.rollback()
            raise PersistenceError(f"persistence transaction failed: {type(exc).__name__}: {exc}") from exc
        finally:
            self._locking = False

    # ---- storage primitives ----------------------------------------------
    def _load_control(self, run_id: str) -> dict[str, Any] | None:
        lock = " FOR UPDATE" if self._locking else ""
        cursor = self._execute(
            f"SELECT run_id, agent_id, agent_version, job_type, environment, objective, "
            f"status, input_hash, validation_hash, checkpoint_seq, checkpoint, budget, "
            f"cancellation_reason, started_at, updated_at, completed_at "
            f"FROM {self._q('agent_runs')} WHERE run_id = %s{lock}",
            (run_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        if row is None:
            return None
        checkpoint = row[10] if isinstance(row[10], Mapping) else {}
        control: dict[str, Any] = {
            "run_id": row[0],
            "agent_id": row[1],
            "agent_version": row[2],
            "job_type": row[3],
            "environment": row[4],
            "objective": row[5],
            "status": row[6],
            "input_hash": row[7],
            "validation_hash": row[8],
            "checkpoint_seq": row[9],
            "events": list(checkpoint.get("events", [])),
            "head_hash": checkpoint.get("head_hash", GENESIS_HASH),
            "checkpoint_label": checkpoint.get("checkpoint_label"),
            "budget": row[11] if isinstance(row[11], Mapping) else {},
            "cancellation_reason": row[12],
            "started_at": _iso(row[13]),
            "updated_at": _iso(row[14]),
            "completed_at": _iso(row[15]),
        }
        return control

    def _checkpoint_jsonb(self, control: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "events": list(control.get("events", [])),
            "head_hash": control.get("head_hash", GENESIS_HASH),
            "checkpoint_label": control.get("checkpoint_label"),
        }

    def _insert_control(self, row: Mapping[str, Any]) -> bool:
        cursor = self._execute(
            f"INSERT INTO {self._q('agent_runs')} "
            f"(run_id, agent_id, agent_version, job_type, environment, objective, status, "
            f" input_hash, validation_hash, checkpoint_seq, checkpoint, budget, started_at, updated_at) "
            f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s) "
            f"ON CONFLICT (run_id) DO NOTHING",
            (
                row["run_id"], row["agent_id"], row["agent_version"], row["job_type"],
                row["environment"], row["objective"], row["status"], row["input_hash"],
                row["validation_hash"], row["checkpoint_seq"],
                self._param("checkpoint", self._checkpoint_jsonb(row)),
                self._param("budget", row.get("budget", {})),
                row["started_at"], row.get("updated_at", row["started_at"]),
            ),
        )
        inserted = cursor.rowcount == 1
        cursor.close()
        return inserted

    def _save_control(self, run_id: str, updates: Mapping[str, Any]) -> None:
        cursor = self._execute(
            f"UPDATE {self._q('agent_runs')} SET status=%s, checkpoint_seq=%s, "
            f"checkpoint=%s::jsonb, updated_at=%s, completed_at=%s, cancellation_reason=%s "
            f"WHERE run_id=%s",
            (
                updates.get("status"), updates.get("checkpoint_seq"),
                self._param("checkpoint", self._checkpoint_jsonb(updates)),
                updates.get("updated_at"), updates.get("completed_at"),
                updates.get("cancellation_reason"), run_id,
            ),
        )
        cursor.close()

    def _insert_append_only(self, table: str, key: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
        columns = _APPEND_COLUMNS[table]
        placeholders = ", ".join(f"%s::jsonb" if col in _JSONB_COLUMNS else "%s" for col in columns)
        params = [self._param(col, row.get(col)) for col in columns]
        cursor = self._execute(
            f"INSERT INTO {self._q(table)} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT {_CONFLICT_TARGET[table]} DO NOTHING",
            params,
        )
        inserted = cursor.rowcount == 1
        cursor.close()
        return inserted

    def _child_ids(self, table: str, run_id: str) -> tuple[str, ...]:
        pk = _CHILD_PK[table]
        if table in ("agent_artifacts", "agent_tool_calls"):
            order = "created_at" if table == "agent_artifacts" else "started_at"
            cursor = self._execute(
                f"SELECT {pk} FROM {self._q(table)} WHERE run_id=%s ORDER BY {order}, {pk}", (run_id,)
            )
        else:  # reviews/scores key on artifact_id -> join to the run via the artifact
            cursor = self._execute(
                f"SELECT c.{pk} FROM {self._q(table)} c "
                f"JOIN {self._q('agent_artifacts')} a ON a.artifact_id = c.artifact_id "
                f"WHERE a.run_id=%s ORDER BY c.created_at, c.{pk}",
                (run_id,),
            )
        ids = tuple(record[0] for record in cursor.fetchall())
        cursor.close()
        return ids

    def _artifact_run(self, artifact_id: str) -> str | None:
        cursor = self._execute(
            f"SELECT run_id FROM {self._q('agent_artifacts')} WHERE artifact_id=%s", (artifact_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        return row[0] if row else None

    def assert_runtime_only(self) -> None:
        """Fail closed if the connected identity looks like the migration executor.

        Requirement: runtime credentials may reach only ``agentic_runtime`` and the
        migration identity must never be required at runtime.
        """

        cursor = self._execute("SELECT current_user")
        who = str(cursor.fetchone()[0])
        cursor.close()
        if "migrator" in who or "migration" in who:
            raise PersistenceError("runtime must not connect with the migration identity")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)
