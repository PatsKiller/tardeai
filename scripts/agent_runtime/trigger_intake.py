"""Governed SHADOW trigger intake queue persistence.

Bounded enqueue, lease, ack, and cursor APIs for the deterministic trigger producer
and queue-backed provider. Writes only to ``agentic_runtime.trigger_intake`` and
``agentic_runtime.trigger_source_cursors`` under an approved runtime writer identity.
"""

from __future__ import annotations

import copy
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import assert_no_secret_material, canonical_hash, canonical_json, utc_now
from .persistence import (
    DEFAULT_RUNTIME_ROLE_ALLOWLIST,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    PersistenceError,
    RuntimeIdentityError,
)

INTAKE_CONTRACT = "agent-runtime-trigger-intake-v1"
SCHEMA = "agentic_runtime"
INTAKE_TABLE = "trigger_intake"
CURSOR_TABLE = "trigger_source_cursors"

INTAKE_STATES = frozenset({"QUEUED", "LEASED", "COMPLETED", "REFUSED_STALE", "FAILED"})
DEFAULT_LEASE_SECONDS = 900


class TriggerIntakeError(PersistenceError):
    """Raised when trigger intake invariants are violated."""


class EnqueueOutcome(str, Enum):
    ENQUEUED = "ENQUEUED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True)
class TriggerCandidate:
    agent_id: str
    trigger_kind: str
    dedup_key: str
    job_type: str
    payload: Mapping[str, Any]
    source_ref: str
    source_hash: str
    source_timestamp: str


@dataclass(frozen=True)
class TriggerIntakeRow:
    intake_id: str
    agent_id: str
    trigger_kind: str
    dedup_key: str
    job_type: str
    payload: Mapping[str, Any]
    payload_hash: str
    source_ref: str
    source_hash: str
    source_timestamp: str
    enqueued_at: str
    state: str
    attempt_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "intake_id": self.intake_id,
            "agent_id": self.agent_id,
            "trigger_kind": self.trigger_kind,
            "dedup_key": self.dedup_key,
            "job_type": self.job_type,
            "payload": dict(self.payload),
            "payload_hash": self.payload_hash,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "source_timestamp": self.source_timestamp,
            "enqueued_at": self.enqueued_at,
            "state": self.state,
            "attempt_count": self.attempt_count,
        }


@runtime_checkable
class TriggerIntakeStore(Protocol):
    def enqueue(self, candidate: TriggerCandidate) -> EnqueueOutcome: ...

    def lease(
        self,
        agent_id: str,
        *,
        limit: int,
        lease_owner: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> list[TriggerIntakeRow]: ...

    def ack_completed(self, intake_id: str, *, run_id: str) -> None: ...

    def ack_refused_stale(self, intake_id: str, *, detail: str = "") -> None: ...

    def ack_failed(self, intake_id: str, *, detail: str = "") -> None: ...

    def return_expired_leases(self) -> int: ...

    def queue_stats(self, agent_id: str | None = None) -> dict[str, Any]: ...

    def get_cursor(self, source_id: str, cursor_key: str) -> str | None: ...

    def set_cursor(
        self,
        source_id: str,
        cursor_key: str,
        cursor_value: str,
        *,
        agent_id: str | None = None,
    ) -> None: ...


def _new_intake_id() -> str:
    return f"ti_{secrets.token_hex(8)}"


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _row_from_mapping(row: Mapping[str, Any]) -> TriggerIntakeRow:
    payload = row.get("payload") or {}
    if not isinstance(payload, Mapping):
        raise TriggerIntakeError("payload must be a mapping")
    return TriggerIntakeRow(
        intake_id=str(row["intake_id"]),
        agent_id=str(row["agent_id"]),
        trigger_kind=str(row["trigger_kind"]),
        dedup_key=str(row["dedup_key"]),
        job_type=str(row["job_type"]),
        payload=dict(payload),
        payload_hash=str(row["payload_hash"]),
        source_ref=str(row["source_ref"]),
        source_hash=str(row["source_hash"]),
        source_timestamp=_parse_ts(str(row["source_timestamp"])).isoformat(),
        enqueued_at=_parse_ts(str(row["enqueued_at"])).isoformat(),
        state=str(row["state"]),
        attempt_count=int(row.get("attempt_count") or 0),
    )


class InMemoryTriggerIntakeStore:
    """Deterministic in-process queue for unit tests."""

    def __init__(self, *, clock=utc_now) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, Any]] = {}
        self._dedup: dict[tuple[str, str, str], str] = {}
        self._cursors: dict[tuple[str, str], dict[str, Any]] = {}

    def _now_dt(self) -> datetime:
        value = self._clock()
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return _parse_ts(str(value))

    def enqueue(self, candidate: TriggerCandidate) -> EnqueueOutcome:
        assert_no_secret_material(candidate.payload)
        key = (candidate.agent_id, candidate.trigger_kind, candidate.dedup_key)
        payload_hash = canonical_hash(candidate.payload)
        with self._lock:
            if key in self._dedup:
                return EnqueueOutcome.DUPLICATE
            intake_id = _new_intake_id()
            now = self._now_dt()
            row = {
                "intake_id": intake_id,
                "agent_id": candidate.agent_id,
                "trigger_kind": candidate.trigger_kind,
                "dedup_key": candidate.dedup_key,
                "job_type": candidate.job_type,
                "payload": copy.deepcopy(dict(candidate.payload)),
                "payload_hash": payload_hash,
                "source_ref": candidate.source_ref,
                "source_hash": candidate.source_hash,
                "source_timestamp": candidate.source_timestamp,
                "enqueued_at": now,
                "state": "QUEUED",
                "lease_owner": None,
                "lease_expires_at": None,
                "attempt_count": 0,
                "last_outcome": None,
                "last_run_id": None,
                "completed_at": None,
            }
            self._rows[intake_id] = row
            self._dedup[key] = intake_id
            return EnqueueOutcome.ENQUEUED

    def lease(
        self,
        agent_id: str,
        *,
        limit: int,
        lease_owner: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> list[TriggerIntakeRow]:
        if limit < 1:
            return []
        now = self._now_dt()
        expires = now + timedelta(seconds=lease_seconds)
        leased: list[TriggerIntakeRow] = []
        with self._lock:
            candidates = sorted(
                (
                    row
                    for row in self._rows.values()
                    if row["agent_id"] == agent_id and row["state"] == "QUEUED"
                ),
                key=lambda row: (_parse_ts(str(row["source_timestamp"])), str(row["enqueued_at"])),
            )
            for row in candidates[:limit]:
                row["state"] = "LEASED"
                row["lease_owner"] = lease_owner
                row["lease_expires_at"] = expires
                row["attempt_count"] = int(row["attempt_count"]) + 1
                leased.append(_row_from_mapping(row))
        return leased

    def _terminal(self, intake_id: str, *, state: str, outcome: str, run_id: str | None = None) -> None:
        with self._lock:
            row = self._rows.get(intake_id)
            if row is None:
                raise TriggerIntakeError(f"unknown intake_id: {intake_id}")
            if row["state"] not in {"QUEUED", "LEASED"}:
                raise TriggerIntakeError(f"intake {intake_id} is not leasable (state={row['state']})")
            row["state"] = state
            row["last_outcome"] = outcome
            row["last_run_id"] = run_id
            row["completed_at"] = self._now_dt()
            row["lease_owner"] = None
            row["lease_expires_at"] = None

    def ack_completed(self, intake_id: str, *, run_id: str) -> None:
        self._terminal(intake_id, state="COMPLETED", outcome="COMPLETED", run_id=run_id)

    def ack_refused_stale(self, intake_id: str, *, detail: str = "") -> None:
        self._terminal(intake_id, state="REFUSED_STALE", outcome=detail or "REFUSED_STALE")

    def ack_failed(self, intake_id: str, *, detail: str = "") -> None:
        self._terminal(intake_id, state="FAILED", outcome=detail or "FAILED")

    def return_expired_leases(self) -> int:
        now = self._now_dt()
        count = 0
        with self._lock:
            for row in self._rows.values():
                if row["state"] != "LEASED":
                    continue
                expires = row.get("lease_expires_at")
                if expires is None or expires >= now:
                    continue
                row["state"] = "QUEUED"
                row["lease_owner"] = None
                row["lease_expires_at"] = None
                count += 1
        return count

    def queue_stats(self, agent_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            rows = [
                row
                for row in self._rows.values()
                if agent_id is None or row["agent_id"] == agent_id
            ]
        queued = [row for row in rows if row["state"] == "QUEUED"]
        leased = [row for row in rows if row["state"] == "LEASED"]
        oldest = None
        if queued:
            oldest_row = min(queued, key=lambda row: _parse_ts(str(row["source_timestamp"])))
            oldest = _parse_ts(str(oldest_row["source_timestamp"])).isoformat()
        return {
            "queued": len(queued),
            "leased": len(leased),
            "completed": sum(1 for row in rows if row["state"] == "COMPLETED"),
            "failed": sum(1 for row in rows if row["state"] == "FAILED"),
            "refused_stale": sum(1 for row in rows if row["state"] == "REFUSED_STALE"),
            "oldest_queued_source_at": oldest,
        }

    def get_cursor(self, source_id: str, cursor_key: str) -> str | None:
        with self._lock:
            row = self._cursors.get((source_id, cursor_key))
            return None if row is None else str(row["cursor_value"])

    def set_cursor(
        self,
        source_id: str,
        cursor_key: str,
        cursor_value: str,
        *,
        agent_id: str | None = None,
    ) -> None:
        with self._lock:
            self._cursors[(source_id, cursor_key)] = {
                "source_id": source_id,
                "cursor_key": cursor_key,
                "agent_id": agent_id,
                "cursor_value": cursor_value,
                "updated_at": self._now_dt(),
            }


class PostgresTriggerIntakeStore:
    """Authoritative trigger queue backend."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        clock=utc_now,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
        role_allowlist: Sequence[str] = DEFAULT_RUNTIME_ROLE_ALLOWLIST,
        verify_identity: bool = True,
    ) -> None:
        if not callable(connection_factory):
            raise TriggerIntakeError("connection_factory must be a zero-arg callable")
        self._factory = connection_factory
        self._clock = clock
        self._timeout_ms = int(statement_timeout_ms)
        self._allowlist = tuple(role_allowlist)
        self._verified = not verify_identity

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        conn = self._factory()
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL statement_timeout = %s", (f"{self._timeout_ms}ms",))
            cur.close()
            if not self._verified:
                self._verify_identity(conn)
                self._verified = True
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _verify_identity(self, conn: Any) -> None:
        cur = conn.cursor()
        cur.execute(
            "SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
        row = cur.fetchone()
        cur.close()
        if row is None:
            raise RuntimeIdentityError("runtime role is not present in pg_roles")
        user, is_super, createdb, createrole, replication, bypassrls = row
        if user not in self._allowlist:
            raise RuntimeIdentityError(f"runtime writer {user!r} is not in the approved allowlist")
        if any((is_super, createdb, createrole, replication, bypassrls)):
            raise RuntimeIdentityError("runtime writer must not hold elevated role attributes")

    def enqueue(self, candidate: TriggerCandidate) -> EnqueueOutcome:
        assert_no_secret_material(candidate.payload)
        payload_hash = canonical_hash(candidate.payload)
        intake_id = _new_intake_id()
        source_ts = _parse_ts(candidate.source_timestamp)
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.{INTAKE_TABLE} (
                    intake_id, agent_id, trigger_kind, dedup_key, job_type,
                    payload, payload_hash, source_ref, source_hash,
                    source_timestamp, enqueued_at, state
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (agent_id, trigger_kind, dedup_key) DO NOTHING
                """,
                (
                    intake_id,
                    candidate.agent_id,
                    candidate.trigger_kind,
                    candidate.dedup_key,
                    candidate.job_type,
                    canonical_json(candidate.payload),
                    payload_hash,
                    candidate.source_ref,
                    candidate.source_hash,
                    source_ts,
                    self._clock(),
                    "QUEUED",
                ),
            )
            inserted = cur.rowcount == 1
            cur.close()
        return EnqueueOutcome.ENQUEUED if inserted else EnqueueOutcome.DUPLICATE

    def lease(
        self,
        agent_id: str,
        *,
        limit: int,
        lease_owner: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> list[TriggerIntakeRow]:
        if limit < 1:
            return []
        # self._clock() (utc_now) returns an ISO string for DB writes elsewhere in
        # this class; lease expiry needs real datetime arithmetic, so parse it
        # rather than assuming a datetime (same class of bug fixed for the
        # in-memory store's lease()).
        now = self._clock()
        now_dt = now if isinstance(now, datetime) else _parse_ts(str(now))
        expires = now_dt + timedelta(seconds=lease_seconds)
        leased: list[TriggerIntakeRow] = []
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT intake_id
                FROM {SCHEMA}.{INTAKE_TABLE}
                WHERE agent_id = %s AND state = 'QUEUED'
                ORDER BY source_timestamp ASC, enqueued_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (agent_id, limit),
            )
            ids = [row[0] for row in cur.fetchall()]
            for intake_id in ids:
                cur.execute(
                    f"""
                    UPDATE {SCHEMA}.{INTAKE_TABLE}
                    SET state = 'LEASED',
                        lease_owner = %s,
                        lease_expires_at = %s,
                        attempt_count = attempt_count + 1
                    WHERE intake_id = %s AND state = 'QUEUED'
                    RETURNING intake_id, agent_id, trigger_kind, dedup_key, job_type,
                              payload, payload_hash, source_ref, source_hash,
                              source_timestamp, enqueued_at, state, attempt_count
                    """,
                    (lease_owner, expires, intake_id),
                )
                row = cur.fetchone()
                if row is None:
                    continue
                leased.append(
                    TriggerIntakeRow(
                        intake_id=row[0],
                        agent_id=row[1],
                        trigger_kind=row[2],
                        dedup_key=row[3],
                        job_type=row[4],
                        payload=row[5] if isinstance(row[5], Mapping) else {},
                        payload_hash=row[6],
                        source_ref=row[7],
                        source_hash=row[8],
                        source_timestamp=_parse_ts(str(row[9])).isoformat(),
                        enqueued_at=_parse_ts(str(row[10])).isoformat(),
                        state=row[11],
                        attempt_count=int(row[12]),
                    )
                )
            cur.close()
        return leased

    def _ack(self, intake_id: str, *, state: str, outcome: str, run_id: str | None = None) -> None:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                UPDATE {SCHEMA}.{INTAKE_TABLE}
                SET state = %s,
                    last_outcome = %s,
                    last_run_id = %s,
                    completed_at = %s,
                    lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE intake_id = %s AND state IN ('QUEUED', 'LEASED')
                """,
                (state, outcome, run_id, self._clock(), intake_id),
            )
            if cur.rowcount != 1:
                cur.close()
                raise TriggerIntakeError(f"intake ack refused for {intake_id}")
            cur.close()

    def ack_completed(self, intake_id: str, *, run_id: str) -> None:
        self._ack(intake_id, state="COMPLETED", outcome="COMPLETED", run_id=run_id)

    def ack_refused_stale(self, intake_id: str, *, detail: str = "") -> None:
        self._ack(intake_id, state="REFUSED_STALE", outcome=detail or "REFUSED_STALE")

    def ack_failed(self, intake_id: str, *, detail: str = "") -> None:
        self._ack(intake_id, state="FAILED", outcome=detail or "FAILED")

    def return_expired_leases(self) -> int:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                UPDATE {SCHEMA}.{INTAKE_TABLE}
                SET state = 'QUEUED',
                    lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE state = 'LEASED'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < %s
                """,
                (self._clock(),),
            )
            count = cur.rowcount
            cur.close()
        return int(count)

    def queue_stats(self, agent_id: str | None = None) -> dict[str, Any]:
        with self._conn() as conn:
            cur = conn.cursor()
            params: list[Any] = []
            where = ""
            if agent_id is not None:
                where = "WHERE agent_id = %s"
                params.append(agent_id)
            cur.execute(
                f"""
                SELECT
                    count(*) FILTER (WHERE state = 'QUEUED') AS queued,
                    count(*) FILTER (WHERE state = 'LEASED') AS leased,
                    count(*) FILTER (WHERE state = 'COMPLETED') AS completed,
                    count(*) FILTER (WHERE state = 'FAILED') AS failed,
                    count(*) FILTER (WHERE state = 'REFUSED_STALE') AS refused_stale,
                    min(source_timestamp) FILTER (WHERE state = 'QUEUED') AS oldest
                FROM {SCHEMA}.{INTAKE_TABLE}
                {where}
                """,
                tuple(params),
            )
            row = cur.fetchone()
            cur.close()
        oldest = row[5]
        return {
            "queued": int(row[0] or 0),
            "leased": int(row[1] or 0),
            "completed": int(row[2] or 0),
            "failed": int(row[3] or 0),
            "refused_stale": int(row[4] or 0),
            "oldest_queued_source_at": oldest.isoformat() if oldest is not None else None,
        }

    def get_cursor(self, source_id: str, cursor_key: str) -> str | None:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT cursor_value
                FROM {SCHEMA}.{CURSOR_TABLE}
                WHERE source_id = %s AND cursor_key = %s
                """,
                (source_id, cursor_key),
            )
            row = cur.fetchone()
            cur.close()
        return None if row is None else str(row[0])

    def set_cursor(
        self,
        source_id: str,
        cursor_key: str,
        cursor_value: str,
        *,
        agent_id: str | None = None,
    ) -> None:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.{CURSOR_TABLE} (
                    source_id, cursor_key, agent_id, cursor_value, updated_at
                ) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (source_id, cursor_key) DO UPDATE
                SET cursor_value = EXCLUDED.cursor_value,
                    agent_id = EXCLUDED.agent_id,
                    updated_at = EXCLUDED.updated_at
                """,
                (source_id, cursor_key, agent_id, cursor_value, self._clock()),
            )
            cur.close()


def intake_row_to_job_request(row: TriggerIntakeRow):
    """Convert a leased intake row into a dispatcher JobRequest."""
    from .agents.dispatcher import JobRequest

    return JobRequest(
        agent_id=row.agent_id,
        job_type=row.job_type,
        input_hash=row.payload_hash,
        enqueued_at=row.source_timestamp,
        dedup_value=row.dedup_key,
        trigger_kind=row.trigger_kind,
        intake_id=row.intake_id,
        payload=dict(row.payload),
    )
