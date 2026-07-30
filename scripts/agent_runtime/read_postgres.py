"""Read-only PostgreSQL reader for the Command Center agent-runtime surface.

Implements :class:`AgentRuntimeReader` against the authoritative eight-table
``agentic_runtime`` schema. It is strictly read-only:

* every operation runs ``SET TRANSACTION READ ONLY`` with a bounded
  ``statement_timeout`` and issues only ``SELECT`` statements;
* the transaction is always rolled back, never committed;
* no DB driver is imported here (a zero-arg ``connection_factory`` is injected),
  so this module holds no mutation, provider, service, schedule, or financial
  authority — it cannot write, and it cannot escalate.

Monitoring events and retrieval evidence are projected from the append-only
RUN_EVENT sentinel rows kept in ``agent_artifacts`` (the immutable journal);
reviews and scores are joined to their run through ``agent_artifacts``.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

from .persistence import (
    DEFAULT_STATEMENT_TIMEOUT_MS,
    RUN_EVENT_TYPE,
    RuntimeIdentityError,
)

READER_CONTRACT = "agent-runtime-postgres-reader-v1"

# Read-only roles are preferred; the read/write runtime roles are also accepted because a
# READ ONLY transaction makes them harmless. Superuser/createdb/etc. are always rejected.
DEFAULT_READER_ROLE_ALLOWLIST = (
    "agentic_runtime_reader",  # A2 packet SHADOW/LAB read-plane identity
    "agentic_runtime_lab_ro",
    "agentic_runtime_shadow_ro",
    "agentic_runtime_lab_rw",
    "agentic_runtime_shadow_rw",
)

# Explicit, safe column projections — never SELECT * and never project raw payload bodies.
_RUN_COLS = (
    "run_id", "agent_id", "agent_version", "job_type", "environment", "status",
    "input_hash", "validation_hash", "retrieval_count", "model_calls", "tool_calls",
    "cost_usd", "checkpoint_seq", "started_at", "updated_at", "completed_at",
)
_ARTIFACT_COLS = (
    "artifact_id", "producer_agent_id", "artifact_type", "payload_hash",
    "input_hash", "validation_hash", "prompt_version", "provider_family", "model", "created_at",
)
_TOOL_CALL_COLS = (
    "tool_call_id", "agent_id", "tool_name", "decision", "decision_reason",
    "arguments_hash", "result_hash", "started_at", "completed_at",
)
_REVIEW_COLS = ("review_id", "artifact_id", "reviewer_agent_id", "verdict", "artifact_hash", "created_at")
_SCORE_COLS = ("score_id", "artifact_id", "scorer_agent_id", "dimensions", "outcome_ref", "created_at")
# Knowledge summaries: metadata only — no statement/facts/source bodies (kept out of
# the read surface so the desk shows lifecycle/provenance without content payloads).
_LESSON_COLS = ("lesson_id", "lesson_version", "lifecycle", "title", "created_by", "reviewed_by", "created_at")
_CASE_COLS = ("case_id", "case_type", "outcome", "outcome_observed_at", "created_at")

_RETRIEVAL_EVENT_TYPES = ("RETRIEVAL_STARTED", "RETRIEVAL_COMPLETED")


def _iso(value: Any) -> Any:
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value


def _as_obj(value: Any) -> Any:
    """JSONB may arrive as a dict (psycopg2 default) or a str; normalize to a Python object."""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


class PostgresAgentRuntimeReader:
    """Read-only ``AgentRuntimeReader`` over the ``agentic_runtime`` schema.

    ``connection_factory`` is a zero-arg callable returning a fresh DB-API 2.0
    connection whose role is an approved read-only/runtime reader.
    """

    contract = READER_CONTRACT
    schema = "agentic_runtime"

    def __init__(
        self,
        connection_factory,
        *,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
        role_allowlist: Sequence[str] = DEFAULT_READER_ROLE_ALLOWLIST,
        verify_identity: bool = True,
    ) -> None:
        if not callable(connection_factory):
            raise ValueError("connection_factory must be a zero-arg callable returning a fresh connection")
        self._factory = connection_factory
        self._timeout_ms = int(statement_timeout_ms)
        self._allowlist = tuple(role_allowlist)
        self._verify = verify_identity
        self._verified = False

    # ---- connection / transaction discipline -----------------------------
    def _q(self, table: str) -> str:
        return f"{self.schema}.{table}"

    @contextmanager
    def _reading(self) -> Iterator[Any]:
        if self._verify and not self._verified:
            self._verify_reader_identity()
            self._verified = True
        conn = self._factory()
        try:
            cur = conn.cursor()
            # READ ONLY must be set before any query in the transaction; timeout bounds every read.
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = %s", (self._timeout_ms,))
            cur.close()
            yield conn
            conn.rollback()  # read-only path never commits
        except Exception:
            _safe_rollback(conn)
            raise
        finally:
            _safe_close(conn)

    def _verify_reader_identity(self) -> None:
        conn = self._factory()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
            row = cur.fetchone()
            cur.close()
            if row is None:
                raise RuntimeIdentityError("reader role is not present in pg_roles")
            user, is_super, createdb, createrole, replication, bypassrls = row
            if user not in self._allowlist:
                raise RuntimeIdentityError(f"reader role {user!r} is not in the approved allowlist")
            if any((is_super, createdb, createrole, replication, bypassrls)):
                raise RuntimeIdentityError("reader role must not hold superuser/createdb/createrole/replication/bypassrls")
            conn.rollback()
        finally:
            _safe_close(conn)

    def _rows(self, conn: Any, sql: str, params: Sequence[Any], cols: Sequence[str]) -> list[dict[str, Any]]:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        fetched = cur.fetchall()
        cur.close()
        return [{c: _iso(v) for c, v in zip(cols, row)} for row in fetched]

    def _run_event_rows(self, conn: Any, run_id: str) -> list[dict[str, Any]]:
        cur = conn.cursor()
        cur.execute(
            f"SELECT payload, payload_hash, created_at FROM {self._q('agent_artifacts')} "
            f"WHERE run_id=%s AND artifact_type=%s",
            (run_id, RUN_EVENT_TYPE),
        )
        fetched = cur.fetchall()
        cur.close()
        events = []
        for payload, payload_hash, created_at in fetched:
            body = _as_obj(payload) or {}
            events.append({"body": body, "event_hash": payload_hash, "created_at": _iso(created_at)})
        events.sort(key=lambda e: int(e["body"].get("sequence", 0)))
        return events

    # ---- AgentRuntimeReader protocol -------------------------------------
    def list_runs(self, *, limit: int, offset: int, agent_id: str | None = None, status: str | None = None) -> Sequence[Mapping[str, Any]]:
        sql = (
            f"SELECT {', '.join(_RUN_COLS)} FROM {self._q('agent_runs')} "
            "WHERE (%s IS NULL OR agent_id = %s) AND (%s IS NULL OR status = %s) "
            "ORDER BY started_at DESC, run_id DESC LIMIT %s OFFSET %s"
        )
        params = (agent_id, agent_id, status, status, int(limit), int(offset))
        with self._reading() as conn:
            return self._rows(conn, sql, params, _RUN_COLS)

    def get_run(self, run_id: str) -> Mapping[str, Any] | None:
        sql = f"SELECT {', '.join(_RUN_COLS)} FROM {self._q('agent_runs')} WHERE run_id=%s"
        with self._reading() as conn:
            rows = self._rows(conn, sql, (run_id,), _RUN_COLS)
        return rows[0] if rows else None

    def list_artifacts(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        sql = (
            f"SELECT {', '.join(_ARTIFACT_COLS)} FROM {self._q('agent_artifacts')} "
            "WHERE run_id=%s AND artifact_type <> %s ORDER BY created_at, artifact_id"
        )
        with self._reading() as conn:
            return self._rows(conn, sql, (run_id, RUN_EVENT_TYPE), _ARTIFACT_COLS)

    def list_tool_calls(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        sql = (
            f"SELECT {', '.join(_TOOL_CALL_COLS)} FROM {self._q('agent_tool_calls')} "
            "WHERE run_id=%s ORDER BY started_at, tool_call_id"
        )
        with self._reading() as conn:
            return self._rows(conn, sql, (run_id,), _TOOL_CALL_COLS)

    def list_reviews(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        cols = ", ".join("c." + c for c in _REVIEW_COLS)
        sql = (
            f"SELECT {cols} FROM {self._q('agent_reviews')} c "
            f"JOIN {self._q('agent_artifacts')} a ON a.artifact_id = c.artifact_id "
            "WHERE a.run_id=%s ORDER BY c.created_at, c.review_id"
        )
        with self._reading() as conn:
            return self._rows(conn, sql, (run_id,), _REVIEW_COLS)

    def list_scores(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        cols = ", ".join("c." + c for c in _SCORE_COLS)
        sql = (
            f"SELECT {cols} FROM {self._q('agent_scores')} c "
            f"JOIN {self._q('agent_artifacts')} a ON a.artifact_id = c.artifact_id "
            "WHERE a.run_id=%s ORDER BY c.created_at, c.score_id"
        )
        with self._reading() as conn:
            rows = self._rows(conn, sql, (run_id,), _SCORE_COLS)
        for row in rows:
            row["dimensions"] = _as_obj(row.get("dimensions")) or {}
        return rows

    def list_retrieval_evidence(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        with self._reading() as conn:
            events = self._run_event_rows(conn, run_id)
        evidence = []
        for event in events:
            body = event["body"]
            if body.get("event_type") not in _RETRIEVAL_EVENT_TYPES:
                continue
            inner = body.get("payload") or {}
            evidence.append({
                "sequence": int(body.get("sequence", 0)),
                "event_type": body.get("event_type"),
                "retrieval_count": inner.get("retrieval_count"),
                "retrieval_hash": inner.get("retrieval_hash"),
                "query_hash": inner.get("query_hash"),
                "occurred_at": body.get("created_at") or event["created_at"],
            })
        return evidence

    def list_monitoring_events(self, run_id: str) -> Sequence[Mapping[str, Any]]:
        with self._reading() as conn:
            events = self._run_event_rows(conn, run_id)
        projected = []
        for event in events:
            body = event["body"]
            inner = body.get("payload") or {}
            projected.append({
                "sequence": int(body.get("sequence", 0)),
                "event_type": body.get("event_type"),
                "status": inner.get("status"),
                "previous_hash": body.get("previous_hash"),
                "event_hash": event["event_hash"],
                "occurred_at": body.get("created_at") or event["created_at"],
            })
        return projected

    def list_lessons(self, *, limit: int, offset: int = 0) -> Sequence[Mapping[str, Any]]:
        cols = ", ".join(_LESSON_COLS)
        sql = (f"SELECT {cols} FROM {self._q('kb_lessons')} "
               "ORDER BY created_at DESC, lesson_id LIMIT %s OFFSET %s")
        with self._reading() as conn:
            return self._rows(conn, sql, (limit, offset), _LESSON_COLS)

    def list_cases(self, *, limit: int, offset: int = 0) -> Sequence[Mapping[str, Any]]:
        cols = ", ".join(_CASE_COLS)
        sql = (f"SELECT {cols} FROM {self._q('kb_cases')} "
               "ORDER BY created_at DESC, case_id LIMIT %s OFFSET %s")
        with self._reading() as conn:
            return self._rows(conn, sql, (limit, offset), _CASE_COLS)


def _safe_rollback(conn: Any) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        try:
            rollback()
        except Exception:
            pass


def _safe_close(conn: Any) -> None:
    closer = getattr(conn, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass
