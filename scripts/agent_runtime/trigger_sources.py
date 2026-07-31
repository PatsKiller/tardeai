"""Read-only deterministic trigger source adapters for the governed SHADOW fleet.

Each adapter emits zero or more :class:`TriggerCandidate` rows from real upstream
evidence. Missing tables, entitlements, or DSN configuration fail closed and
enqueue nothing — never a fixture or synthetic seed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from .contracts import canonical_hash
from .trigger_intake import TriggerCandidate

SOURCE_DSN_ENV = "AGENT_RUNTIME_SOURCE_DSN"
SOURCE_PROBE_ENV = "AGENT_RUNTIME_SOURCE_PROBE"


class SourceState(str, Enum):
    READY = "READY"
    BLOCKED_SOURCE = "BLOCKED_SOURCE"
    STALE_SOURCE = "STALE_SOURCE"
    NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass(frozen=True)
class SourceProbe:
    source_id: str
    state: SourceState
    detail: str
    required_tables: tuple[str, ...] = ()
    last_observed_at: str | None = None


@dataclass(frozen=True)
class AdapterResult:
    source_id: str
    probe: SourceProbe
    candidates: tuple[TriggerCandidate, ...]
    cursor_updates: tuple[tuple[str, str, str], ...] = ()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    return str(value)


def _connection_factory(dsn: str) -> Callable[[], Any]:
    import importlib

    psycopg2 = importlib.import_module("psycopg2")

    def factory() -> Any:
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        return conn

    return factory


def _table_exists(conn: Any, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (table,))
    row = cur.fetchone()
    cur.close()
    return row is not None and row[0] is not None


def _probe_tables(source_id: str, tables: Sequence[str], conn: Any | None) -> SourceProbe:
    if conn is None:
        return SourceProbe(
            source_id=source_id,
            state=SourceState.NOT_CONFIGURED,
            detail=f"{SOURCE_DSN_ENV} is not configured.",
            required_tables=tuple(tables),
        )
    missing = [table for table in tables if not _table_exists(conn, table)]
    if missing:
        return SourceProbe(
            source_id=source_id,
            state=SourceState.BLOCKED_SOURCE,
            detail=f"Missing required tables: {', '.join(missing)}",
            required_tables=tuple(tables),
        )
    return SourceProbe(
        source_id=source_id,
        state=SourceState.READY,
        detail="Source reader connected.",
        required_tables=tuple(tables),
        last_observed_at=_utc_now().isoformat(),
    )


def _fetch_rows(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(sql, params)
    columns = [desc[0] for desc in cur.description or ()]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def _candidate(
    *,
    agent_id: str,
    trigger_kind: str,
    dedup_key: str,
    job_type: str,
    payload: Mapping[str, Any],
    source_ref: str,
    source_timestamp: str,
) -> TriggerCandidate:
    return TriggerCandidate(
        agent_id=agent_id,
        trigger_kind=trigger_kind,
        dedup_key=dedup_key,
        job_type=job_type,
        payload=payload,
        source_ref=source_ref,
        source_hash=canonical_hash(payload),
        source_timestamp=source_timestamp,
    )


def _watch_artifact_adapters(cursor_value: str | None, *, limit: int = 32) -> AdapterResult:
    source_id = "watch:artifacts"
    tables = ("decision_packets", "watchlist_items")
    dsn = os.environ.get(SOURCE_DSN_ENV, "").strip()
    conn = None
    try:
        if dsn:
            conn = _connection_factory(dsn)()
        probe = _probe_tables(source_id, tables, conn)
        if probe.state != SourceState.READY or conn is None:
            return AdapterResult(source_id, probe, ())

        since = cursor_value or "1970-01-01T00:00:00+00:00"
        rows = _fetch_rows(
            conn,
            """
            SELECT dp.packet_id,
                   dp.symbol,
                   dp.generated_at,
                   dp.packet
            FROM decision_packets dp
            JOIN watchlist_items wi ON upper(wi.symbol) = upper(dp.symbol)
            WHERE dp.generated_at > %s
            ORDER BY dp.generated_at ASC
            LIMIT %s
            """,
            (since, limit),
        )
        candidates: list[TriggerCandidate] = []
        newest = cursor_value
        for row in rows:
            ts = _iso(row["generated_at"])
            newest = ts
            payload = {
                "packet_id": row["packet_id"],
                "symbol": row["symbol"],
                "packet": row["packet"],
                "source": source_id,
            }
            dedup = f"{source_id}:{row['packet_id']}"
            for agent_id, job_type in (
                ("sentinel", "watch_ticket_review"),
                ("maria", "fundamental_research_review"),
                ("vega", "technical_structure_review"),
                ("pulse", "microstructure_review"),
            ):
                candidates.append(
                    _candidate(
                        agent_id=agent_id,
                        trigger_kind="WATCH_ARTIFACT_CHANGED",
                        dedup_key=f"{dedup}:{agent_id}",
                        job_type=job_type,
                        payload={**payload, "target_agent": agent_id},
                        source_ref=f"{source_id}:{row['packet_id']}",
                        source_timestamp=ts,
                    )
                )
        cursor_updates = ()
        if newest and newest != cursor_value:
            cursor_updates = ((source_id, "generated_at", newest),)
        return AdapterResult(source_id, probe, tuple(candidates), cursor_updates)
    finally:
        if conn is not None:
            conn.close()


def _packet_rebuild_adapter(cursor_value: str | None, *, limit: int = 16) -> AdapterResult:
    source_id = "watch:refresh_jobs"
    tables = ("watch_decision_refresh_jobs",)
    dsn = os.environ.get(SOURCE_DSN_ENV, "").strip()
    conn = None
    try:
        if dsn:
            conn = _connection_factory(dsn)()
        probe = _probe_tables(source_id, tables, conn)
        if probe.state != SourceState.READY or conn is None:
            return AdapterResult(source_id, probe, ())

        since = cursor_value or "1970-01-01T00:00:00+00:00"
        rows = _fetch_rows(
            conn,
            """
            SELECT job_id, symbol, state, completed_at, packet_id_after
            FROM watch_decision_refresh_jobs
            WHERE state = 'COMPLETE'
              AND completed_at > %s
              AND packet_id_after IS NOT NULL
            ORDER BY completed_at ASC
            LIMIT %s
            """,
            (since, limit),
        )
        candidates: list[TriggerCandidate] = []
        newest = cursor_value
        for row in rows:
            ts = _iso(row["completed_at"])
            newest = ts
            payload = {
                "job_id": row["job_id"],
                "symbol": row["symbol"],
                "packet_id_after": row["packet_id_after"],
                "source": source_id,
            }
            dedup = f"{source_id}:{row['job_id']}"
            for agent_id, job_type, trigger_kind in (
                ("sentinel", "decision_integrity_review", "PACKET_REBUILD"),
                ("vega", "technical_structure_review", "PACKET_REBUILD"),
            ):
                candidates.append(
                    _candidate(
                        agent_id=agent_id,
                        trigger_kind=trigger_kind,
                        dedup_key=f"{dedup}:{agent_id}",
                        job_type=job_type,
                        payload={**payload, "target_agent": agent_id},
                        source_ref=f"{source_id}:{row['job_id']}",
                        source_timestamp=ts,
                    )
                )
        cursor_updates = ()
        if newest and newest != cursor_value:
            cursor_updates = ((source_id, "completed_at", newest),)
        return AdapterResult(source_id, probe, tuple(candidates), cursor_updates)
    finally:
        if conn is not None:
            conn.close()


def _outcome_adapter(cursor_value: str | None, *, limit: int = 32) -> AdapterResult:
    source_id = "outcomes:recommendations"
    tables = ("agent_recommendation_outcomes",)
    dsn = os.environ.get(SOURCE_DSN_ENV, "").strip()
    conn = None
    try:
        if dsn:
            conn = _connection_factory(dsn)()
        probe = _probe_tables(source_id, tables, conn)
        if probe.state != SourceState.READY or conn is None:
            return AdapterResult(source_id, probe, ())

        since = cursor_value or "1970-01-01T00:00:00+00:00"
        rows = _fetch_rows(
            conn,
            """
            SELECT agent_name, symbol, verdict, scored_at, war_id, trade_id, recommendation
            FROM agent_recommendation_outcomes
            WHERE scored_at > %s
            ORDER BY scored_at ASC
            LIMIT %s
            """,
            (since, limit),
        )
        candidates = []
        newest = cursor_value
        for row in rows:
            ts = _iso(row["scored_at"])
            newest = ts
            ref = row.get("war_id") or row.get("trade_id") or f"{row['agent_name']}:{row['symbol']}:{ts}"
            payload = {
                "agent_name": row["agent_name"],
                "symbol": row["symbol"],
                "verdict": row["verdict"],
                "recommendation": row.get("recommendation"),
                "war_id": row.get("war_id"),
                "trade_id": row.get("trade_id"),
                "source": source_id,
            }
            candidates.append(
                _candidate(
                    agent_id="darwin",
                    trigger_kind="OUTCOME_EVIDENCE_AVAILABLE",
                    dedup_key=f"{source_id}:{ref}",
                    job_type="outcome_join",
                    payload=payload,
                    source_ref=f"{source_id}:{ref}",
                    source_timestamp=ts,
                )
            )
        cursor_updates = ()
        if newest and newest != cursor_value:
            cursor_updates = ((source_id, "scored_at", newest),)
        return AdapterResult(source_id, probe, tuple(candidates), cursor_updates)
    finally:
        if conn is not None:
            conn.close()


def _kb_lessons_adapter(cursor_value: str | None, *, limit: int = 32) -> AdapterResult:
    source_id = "kb:candidate_lessons"
    tables = ("agentic_runtime.kb_lessons",)
    dsn = os.environ.get(SOURCE_DSN_ENV, "").strip()
    conn = None
    try:
        if dsn:
            conn = _connection_factory(dsn)()
        probe = _probe_tables(source_id, tables, conn)
        if probe.state != SourceState.READY or conn is None:
            return AdapterResult(source_id, probe, ())

        since = cursor_value or "1970-01-01T00:00:00+00:00"
        rows = _fetch_rows(
            conn,
            """
            SELECT lesson_id, title, lifecycle, created_at, statement, provenance
            FROM agentic_runtime.kb_lessons
            WHERE lifecycle = 'CANDIDATE'
              AND created_at > %s
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (since, limit),
        )
        candidates = []
        newest = cursor_value
        for row in rows:
            ts = _iso(row["created_at"])
            newest = ts
            payload = {
                "lesson_id": row["lesson_id"],
                "title": row["title"],
                "lifecycle": row["lifecycle"],
                "statement": row["statement"],
                "provenance": row["provenance"],
                "source": source_id,
            }
            candidates.append(
                _candidate(
                    agent_id="iris",
                    trigger_kind="CANDIDATE_LESSON",
                    dedup_key=f"{source_id}:{row['lesson_id']}",
                    job_type="lesson_review",
                    payload=payload,
                    source_ref=f"{source_id}:{row['lesson_id']}",
                    source_timestamp=ts,
                )
            )
        cursor_updates = ()
        if newest and newest != cursor_value:
            cursor_updates = ((source_id, "created_at", newest),)
        return AdapterResult(source_id, probe, tuple(candidates), cursor_updates)
    finally:
        if conn is not None:
            conn.close()


def _incident_adapter(cursor_value: str | None, *, limit: int = 16) -> AdapterResult:
    source_id = "incidents:alert"
    tables = ("alert_incidents",)
    dsn = os.environ.get(SOURCE_DSN_ENV, "").strip()
    conn = None
    try:
        if dsn:
            conn = _connection_factory(dsn)()
        probe = _probe_tables(source_id, tables, conn)
        if probe.state != SourceState.READY or conn is None:
            return AdapterResult(source_id, probe, ())

        since = cursor_value or "1970-01-01T00:00:00+00:00"
        rows = _fetch_rows(
            conn,
            """
            SELECT incident_id, alert_type, source_system, first_seen_at, last_seen_at, severity, status
            FROM alert_incidents
            WHERE first_seen_at > %s
              AND status = 'open'
            ORDER BY first_seen_at ASC
            LIMIT %s
            """,
            (since, limit),
        )
        candidates = []
        newest = cursor_value
        for row in rows:
            ts = _iso(row["first_seen_at"])
            newest = ts
            payload = dict(row)
            payload["source"] = source_id
            candidates.append(
                _candidate(
                    agent_id="aegis",
                    trigger_kind="INCIDENT_OPENED",
                    dedup_key=f"{source_id}:{row['incident_id']}",
                    job_type="incident_review",
                    payload=payload,
                    source_ref=f"{source_id}:{row['incident_id']}",
                    source_timestamp=ts,
                )
            )
        cursor_updates = ()
        if newest and newest != cursor_value:
            cursor_updates = ((source_id, "first_seen_at", newest),)
        return AdapterResult(source_id, probe, tuple(candidates), cursor_updates)
    finally:
        if conn is not None:
            conn.close()


def _research_adapter(cursor_value: str | None, *, limit: int = 16) -> AdapterResult:
    source_id = "research:hermes"
    tables = ("hermes_discovery_candidates",)
    dsn = os.environ.get(SOURCE_DSN_ENV, "").strip()
    conn = None
    try:
        if dsn:
            conn = _connection_factory(dsn)()
        probe = _probe_tables(source_id, tables, conn)
        if probe.state != SourceState.READY or conn is None:
            return AdapterResult(source_id, probe, ())

        since = cursor_value or "1970-01-01T00:00:00+00:00"
        rows = _fetch_rows(
            conn,
            """
            SELECT id AS ref_id,
                   normalized_key,
                   label,
                   summary,
                   extracted_symbols,
                   status,
                   created_at
            FROM hermes_discovery_candidates
            WHERE created_at > %s
              AND status IN ('READY_FOR_REVIEW', 'NEEDS_VALIDATION', 'DISCOVERED')
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (since, limit),
        )
        candidates = []
        newest = cursor_value
        for row in rows:
            ts = _iso(row["created_at"])
            newest = ts
            payload = dict(row)
            payload["source"] = source_id
            ref = row["ref_id"]
            for agent_id, job_type in (("alex", "cio_synthesis"), ("hermes", "hypothesis_discovery")):
                candidates.append(
                    _candidate(
                        agent_id=agent_id,
                        trigger_kind="RESEARCH_REQUEST",
                        dedup_key=f"{source_id}:{ref}:{agent_id}",
                        job_type=job_type,
                        payload={**payload, "target_agent": agent_id},
                        source_ref=f"{source_id}:{ref}",
                        source_timestamp=ts,
                    )
                )
        cursor_updates = ()
        if newest and newest != cursor_value:
            cursor_updates = ((source_id, "created_at", newest),)
        return AdapterResult(source_id, probe, tuple(candidates), cursor_updates)
    finally:
        if conn is not None:
            conn.close()


def _sweep_adapter(agent_id: str, job_type: str, source_id: str, *, trigger_kind: str = "SCHEDULED_SWEEP") -> AdapterResult:
    """Bounded sweep when producer timer fires; no upstream row required."""
    now = _utc_now().isoformat()
    bucket = now[:16]
    payload = {"agent_id": agent_id, "sweep_bucket": bucket, "source": source_id}
    candidate = _candidate(
        agent_id=agent_id,
        trigger_kind=trigger_kind,
        dedup_key=f"{source_id}:{agent_id}:{bucket}",
        job_type=job_type,
        payload=payload,
        source_ref=f"{source_id}:{bucket}",
        source_timestamp=now,
    )
    probe = SourceProbe(
        source_id=source_id,
        state=SourceState.READY,
        detail="Sweep producer tick.",
        last_observed_at=now,
    )
    return AdapterResult(source_id, probe, (candidate,))


SWEEP_AGENTS: dict[str, tuple[str, str]] = {
    "darwin": ("artifact_scoring", "sweep:darwin"),
    "argus": ("population_integrity_scan", "sweep:argus"),
    "risk_agent": ("risk_evidence_review", "sweep:risk"),
    "atlas": ("durable_workflow_orchestration", "sweep:atlas"),
    "concierge": ("operator_status", "sweep:concierge"),
    "steph": ("allocation_review", "sweep:steph"),
    "tax_agent": ("tax_constraint_review", "sweep:tax"),
}


def _alert_incidents_adapter(
    cursor_value: str | None,
    *,
    source_id: str,
    alert_types: tuple[str, ...],
    agents: Sequence[tuple[str, str, str]],
    limit: int = 16,
) -> AdapterResult:
    """Map open alert_incidents rows to bounded FLEET review jobs (read-only)."""
    tables = ("alert_incidents",)
    dsn = os.environ.get(SOURCE_DSN_ENV, "").strip()
    conn = None
    try:
        if dsn:
            conn = _connection_factory(dsn)()
        probe = _probe_tables(source_id, tables, conn)
        if probe.state != SourceState.READY or conn is None:
            return AdapterResult(source_id, probe, ())

        since = cursor_value or "1970-01-01T00:00:00+00:00"
        type_clause = " OR ".join("alert_type ILIKE %s" for _ in alert_types)
        params: list[Any] = [since, *alert_types, limit]
        rows = _fetch_rows(
            conn,
            f"""
            SELECT incident_id, alert_type, source_system, first_seen_at, severity, status, symbol
            FROM alert_incidents
            WHERE first_seen_at > %s
              AND status = 'open'
              AND ({type_clause})
            ORDER BY first_seen_at ASC
            LIMIT %s
            """,
            tuple(params),
        )
        candidates: list[TriggerCandidate] = []
        newest = cursor_value
        for row in rows:
            ts = _iso(row["first_seen_at"])
            newest = ts
            payload = {**row, "source": source_id}
            ref = row["incident_id"]
            for agent_id, job_type, trigger_kind in agents:
                candidates.append(
                    _candidate(
                        agent_id=agent_id,
                        trigger_kind=trigger_kind,
                        dedup_key=f"{source_id}:{ref}:{agent_id}",
                        job_type=job_type,
                        payload={**payload, "target_agent": agent_id},
                        source_ref=f"{source_id}:{ref}",
                        source_timestamp=ts,
                    )
                )
        cursor_updates = ()
        if newest and newest != cursor_value:
            cursor_updates = ((source_id, "first_seen_at", newest),)
        return AdapterResult(source_id, probe, tuple(candidates), cursor_updates)
    finally:
        if conn is not None:
            conn.close()


def _alerts_risk_adapter(cursor_value: str | None) -> AdapterResult:
    return _alert_incidents_adapter(
        cursor_value,
        source_id="alerts:risk",
        alert_types=("%stop%", "%risk%", "%breach%"),
        agents=(("risk_agent", "risk_evidence_review", "QUALITY_EXCEPTION"),),
    )


def _alerts_proposals_adapter(cursor_value: str | None) -> AdapterResult:
    return _alert_incidents_adapter(
        cursor_value,
        source_id="alerts:proposals",
        alert_types=("%proposal%", "%approval%"),
        agents=(
            ("steph", "allocation_review", "SCHEDULED_SWEEP"),
            ("aegis", "incident_review", "INCIDENT_OPENED"),
        ),
    )


def _reflection_nightly_adapter() -> AdapterResult:
    source_id = "nightly:reflection"
    now = _utc_now()
    bucket = now.date().isoformat()
    payload = {"agent_id": "reflection", "nightly_bucket": bucket, "source": source_id}
    candidate = _candidate(
        agent_id="reflection",
        trigger_kind="NIGHTLY_BATCH",
        dedup_key=f"{source_id}:{bucket}",
        job_type="nightly_reflection",
        payload=payload,
        source_ref=f"{source_id}:{bucket}",
        source_timestamp=now.isoformat(),
    )
    probe = SourceProbe(
        source_id=source_id,
        state=SourceState.READY,
        detail="Nightly reflection batch.",
        last_observed_at=now.isoformat(),
    )
    return AdapterResult(source_id, probe, (candidate,))


ADAPTERS: dict[str, Callable[[str | None], AdapterResult]] = {
    "watch:artifacts": lambda cursor: _watch_artifact_adapters(cursor),
    "watch:refresh_jobs": lambda cursor: _packet_rebuild_adapter(cursor),
    "outcomes:recommendations": lambda cursor: _outcome_adapter(cursor),
    "kb:candidate_lessons": lambda cursor: _kb_lessons_adapter(cursor),
    "incidents:alert": lambda cursor: _incident_adapter(cursor),
    "research:hermes": lambda cursor: _research_adapter(cursor),
    "alerts:risk": lambda cursor: _alerts_risk_adapter(cursor),
    "alerts:proposals": lambda cursor: _alerts_proposals_adapter(cursor),
}

ADAPTER_CURSOR_KEYS: dict[str, str] = {
    "watch:artifacts": "generated_at",
    "watch:refresh_jobs": "completed_at",
    "outcomes:recommendations": "scored_at",
    "kb:candidate_lessons": "created_at",
    "incidents:alert": "first_seen_at",
    "research:hermes": "created_at",
    "alerts:risk": "first_seen_at",
    "alerts:proposals": "first_seen_at",
}


def probe_all_sources() -> list[SourceProbe]:
    """Read-only source readiness for operations/health surfaces."""
    if os.environ.get(SOURCE_PROBE_ENV, "").strip().lower() in {"0", "false", "no"}:
        return [
            SourceProbe(
                source_id="*",
                state=SourceState.NOT_CONFIGURED,
                detail="Source probe disabled.",
            )
        ]
    probes: list[SourceProbe] = []
    for source_id, adapter in ADAPTERS.items():
        result = adapter(None)
        probes.append(result.probe)
    for source_id, (job_type, sweep_id) in SWEEP_AGENTS.items():
        probes.append(
            SourceProbe(
                source_id=sweep_id,
                state=SourceState.READY,
                detail=f"Sweep adapter for {source_id}.",
            )
        )
    probes.append(
        SourceProbe(
            source_id="nightly:reflection",
            state=SourceState.READY,
            detail="Nightly reflection adapter.",
        )
    )
    return probes


def run_adapter(source_id: str, cursor_value: str | None) -> AdapterResult:
    if source_id in ADAPTERS:
        return ADAPTERS[source_id](cursor_value)
    if source_id.startswith("sweep:"):
        agent_id = source_id.split(":", 1)[1]
        job_type, canonical = SWEEP_AGENTS.get(agent_id, ("bounded_sweep", source_id))
        return _sweep_adapter(agent_id, job_type, canonical)
    if source_id == "nightly:reflection":
        return _reflection_nightly_adapter()
    return AdapterResult(
        source_id,
        SourceProbe(source_id, SourceState.BLOCKED_SOURCE, "Unknown source adapter."),
        (),
    )
