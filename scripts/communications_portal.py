#!/usr/bin/env python3
"""communications_portal.py — read-only projections for /v3/communications.

Reads CommunicationEvent ledger + ChannelDelivery + subject memory via
scripts.lib.comms memory snapshots and optional DB. Never calls Telegram,
Slack, or any provider adapter.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _jsonish(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, (bytes, memoryview)):
        try:
            v = bytes(v).decode("utf-8")
        except Exception:
            return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return v
        if s[0] in "{[":
            try:
                return json.loads(s)
            except Exception:
                return v
        return v
    return v


def _project_event(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Operator-facing event projection (ledger fields only)."""
    return {
        "event_id": row.get("event_id"),
        "schema_version": row.get("schema_version"),
        "direction": row.get("direction"),
        "event_type": row.get("event_type") or row.get("type"),
        "type": row.get("event_type") or row.get("type"),
        "message_class": row.get("message_class"),
        "severity": row.get("severity"),
        "audience": row.get("audience"),
        "producer": row.get("producer"),
        "subject_key": row.get("subject_key"),
        "thread_id": row.get("thread_id"),
        "correlation_id": row.get("correlation_id"),
        "incident_id": row.get("incident_id"),
        "curation_mode": row.get("curation_mode"),
        "retention_class": row.get("retention_class"),
        "knowledge_status": row.get("knowledge_status"),
        "knowledge_eligibility": row.get("knowledge_eligibility"),
        "short_summary": row.get("short_summary"),
        "sanitized_body": row.get("sanitized_body"),
        "status": row.get("knowledge_status") or row.get("status"),
        "created_at": _iso(row.get("created_at")),
        "observed_at": _iso(row.get("observed_at")),
        "gateway_mode_at_write": row.get("gateway_mode_at_write"),
        "entity_refs": _jsonish(row.get("entity_refs")) or {},
        "protected_facts": _jsonish(row.get("protected_facts")) or {},
        "provider_coordinates": _jsonish(row.get("provider_coordinates")) or {},
        "delivery_policy": _jsonish(row.get("delivery_policy")) or {},
        "channels": row.get("channels") or (_jsonish(row.get("delivery_policy")) or {}).get("channels"),
        "idempotency_key": row.get("idempotency_key"),
        "source": source,
    }


def _project_delivery(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "delivery_id": row.get("delivery_id"),
        "event_id": row.get("event_id"),
        "channel": row.get("channel"),
        "attempt_id": row.get("attempt_id"),
        "status": row.get("status"),
        "schema_version": row.get("schema_version"),
        "adapter_version": row.get("adapter_version"),
        "provider_message_id": row.get("provider_message_id"),
        "error_taxonomy": row.get("error_taxonomy"),
        "reserved_at": _iso(row.get("reserved_at")),
        "sent_at": _iso(row.get("sent_at")),
        "completed_at": _iso(row.get("completed_at")),
        "idempotency_key": row.get("idempotency_key"),
        "chunk_count": row.get("chunk_count"),
        "provider_coordinates": _jsonish(row.get("provider_coordinates")) or {},
        "source": source,
    }


def _project_subject(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "subject_key": row.get("subject_key"),
        "domain": row.get("domain"),
        "canonical_entities": _jsonish(row.get("canonical_entities")) or {},
        "aliases": _jsonish(row.get("aliases")) or [],
        "first_activity_at": _iso(row.get("first_activity_at")),
        "last_activity_at": _iso(row.get("last_activity_at")),
        "latest_state": _jsonish(row.get("latest_state")) or {},
        "open_questions": _jsonish(row.get("open_questions")) or [],
        "event_count": row.get("event_count"),
        "persisted": row.get("persisted") or source,
        "source": source,
    }


def _events_db_conn():
    """Best-effort DB when communication_events exists; else None."""
    try:
        from scripts.lib.comms.client import _db_conn
    except Exception:
        try:
            from lib.comms.client import _db_conn  # type: ignore
        except Exception:
            return None
    try:
        return _db_conn()
    except Exception:
        return None


def _deliveries_db_conn():
    try:
        from scripts.lib.comms.delivery import _db_conn
    except Exception:
        try:
            from lib.comms.delivery import _db_conn  # type: ignore
        except Exception:
            return None
    try:
        return _db_conn()
    except Exception:
        return None


def _subjects_db_conn():
    try:
        from scripts.lib.comms.subject_memory import _db_conn
    except Exception:
        try:
            from lib.comms.subject_memory import _db_conn  # type: ignore
        except Exception:
            return None
    try:
        return _db_conn()
    except Exception:
        return None


def _memory_events() -> list[dict[str, Any]]:
    try:
        from scripts.lib.comms.client import memory_store_snapshot
    except Exception:
        from lib.comms.client import memory_store_snapshot  # type: ignore
    snap = memory_store_snapshot()
    return [_project_event(dict(v), source="memory") for v in snap.values()]


def _memory_deliveries() -> list[dict[str, Any]]:
    try:
        from scripts.lib.comms.delivery import memory_delivery_snapshot
    except Exception:
        from lib.comms.delivery import memory_delivery_snapshot  # type: ignore
    snap = memory_delivery_snapshot()
    return [_project_delivery(dict(v), source="memory") for v in snap.values()]


def _memory_subjects() -> list[dict[str, Any]]:
    try:
        from scripts.lib.comms.subject_memory import memory_subject_snapshot
    except Exception:
        from lib.comms.subject_memory import memory_subject_snapshot  # type: ignore
    snap = memory_subject_snapshot()
    subjects = snap.get("subjects") or {}
    membership = snap.get("membership") or []
    counts: dict[str, int] = {}
    for m in membership:
        sk = m.get("subject_key")
        if sk:
            counts[sk] = counts.get(sk, 0) + 1
    out = []
    for sk, row in subjects.items():
        proj = _project_subject(dict(row), source="memory")
        proj["event_count"] = counts.get(sk, proj.get("event_count") or 0)
        out.append(proj)
    return out


def _db_list_events(
    *, limit: int, subject_key: str | None, status: str | None
) -> list[dict[str, Any]] | None:
    conn = _events_db_conn()
    if conn is None:
        return None
    try:
        clauses = ["1=1"]
        params: list[Any] = []
        if subject_key:
            clauses.append("subject_key = %s")
            params.append(subject_key)
        if status:
            clauses.append("(knowledge_status = %s OR COALESCE(payload->>'status', '') = %s)")
            params.extend([status, status])
        sql = f"""
            SELECT event_id, schema_version, direction, event_type, message_class,
                   severity, audience, producer, subject_key, thread_id, correlation_id,
                   incident_id, curation_mode, retention_class, knowledge_status,
                   knowledge_eligibility, short_summary, sanitized_body, created_at,
                   observed_at, gateway_mode_at_write, entity_refs, protected_facts,
                   provider_coordinates, delivery_policy, idempotency_key
              FROM communication_events
             WHERE {' AND '.join(clauses)}
             ORDER BY created_at DESC NULLS LAST
             LIMIT %s
        """
        params.append(int(limit))
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return [_project_event(r, source="db") for r in rows]
    except Exception:
        return None


def _db_get_event(event_id: str) -> dict[str, Any] | None:
    conn = _events_db_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, schema_version, direction, event_type, message_class,
                       severity, audience, producer, subject_key, thread_id, correlation_id,
                       incident_id, curation_mode, retention_class, knowledge_status,
                       knowledge_eligibility, short_summary, sanitized_body, created_at,
                       observed_at, gateway_mode_at_write, entity_refs, protected_facts,
                       provider_coordinates, delivery_policy, idempotency_key, payload
                  FROM communication_events
                 WHERE event_id = %s
                """,
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
        return _project_event(dict(zip(cols, row)), source="db")
    except Exception:
        return None


def _db_list_deliveries(*, event_id: str | None, limit: int) -> list[dict[str, Any]] | None:
    conn = _deliveries_db_conn()
    if conn is None:
        return None
    try:
        clauses = ["1=1"]
        params: list[Any] = []
        if event_id:
            clauses.append("event_id = %s")
            params.append(event_id)
        sql = f"""
            SELECT delivery_id, event_id, channel, attempt_id, status, schema_version,
                   adapter_version, provider_message_id, error_taxonomy, reserved_at,
                   sent_at, completed_at, idempotency_key, chunk_count, provider_coordinates
              FROM communication_deliveries
             WHERE {' AND '.join(clauses)}
             ORDER BY reserved_at DESC NULLS LAST
             LIMIT %s
        """
        params.append(int(limit))
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return [_project_delivery(r, source="db") for r in rows]
    except Exception:
        return None


def _db_list_subjects(*, limit: int) -> list[dict[str, Any]] | None:
    conn = _subjects_db_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.subject_key, s.domain, s.canonical_entities, s.aliases,
                       s.first_activity_at, s.last_activity_at, s.latest_state,
                       s.open_questions,
                       (SELECT COUNT(*) FROM communication_thread_membership m
                         WHERE m.subject_key = s.subject_key) AS event_count
                  FROM communication_subjects s
                 ORDER BY s.last_activity_at DESC NULLS LAST
                 LIMIT %s
                """,
                (int(limit),),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return [_project_subject(r, source="db") for r in rows]
    except Exception:
        return None


def _sort_created_desc(rows: list[dict[str, Any]], key: str = "created_at") -> list[dict[str, Any]]:
    def _k(r: dict[str, Any]):
        v = r.get(key) or r.get("last_activity_at") or r.get("reserved_at") or ""
        return str(v)

    return sorted(rows, key=_k, reverse=True)


def list_events(
    limit: int = 100,
    subject_key: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List CommunicationEvent projections. Prefer DB; fall back to memory."""
    lim = max(1, min(int(limit or 100), 500))
    sk = (subject_key or "").strip() or None
    st = (status or "").strip() or None

    db_rows = _db_list_events(limit=lim, subject_key=sk, status=st)
    if db_rows is not None and len(db_rows) > 0:
        return {
            "ok": True,
            "events": db_rows[:lim],
            "total": len(db_rows),
            "source": "db",
            "limit": lim,
            "filters": {"subject_key": sk, "status": st},
        }

    mem = _memory_events()
    if sk:
        mem = [e for e in mem if e.get("subject_key") == sk]
    if st:
        mem = [
            e
            for e in mem
            if (e.get("knowledge_status") == st or e.get("status") == st)
        ]
    mem = _sort_created_desc(mem)[:lim]

    if db_rows is not None and len(db_rows) == 0 and not mem:
        source = "empty"
        events: list[dict[str, Any]] = []
    elif mem:
        source = "memory"
        events = mem
    elif db_rows is not None:
        source = "empty"
        events = []
    else:
        source = "empty" if not mem else "memory"
        events = mem

    return {
        "ok": True,
        "events": events,
        "total": len(events),
        "source": source,
        "limit": lim,
        "filters": {"subject_key": sk, "status": st},
    }


def get_event(event_id: str) -> dict[str, Any]:
    """Fetch one event by id from DB or memory."""
    eid = (event_id or "").strip()
    if not eid:
        return {"ok": False, "error": "event_id required", "event": None, "source": "empty"}

    db_row = _db_get_event(eid)
    if db_row is not None:
        return {"ok": True, "event": db_row, "source": "db"}

    for row in _memory_events():
        if row.get("event_id") == eid:
            return {"ok": True, "event": row, "source": "memory"}

    return {"ok": False, "error": "not found", "event": None, "source": "empty"}


def list_deliveries(event_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    """List ChannelDelivery@v1 projections (RESERVED stubs included)."""
    lim = max(1, min(int(limit or 200), 500))
    eid = (event_id or "").strip() or None

    db_rows = _db_list_deliveries(event_id=eid, limit=lim)
    if db_rows is not None and len(db_rows) > 0:
        return {
            "ok": True,
            "deliveries": db_rows[:lim],
            "total": len(db_rows),
            "source": "db",
            "filters": {"event_id": eid},
        }

    mem = _memory_deliveries()
    if eid:
        mem = [d for d in mem if d.get("event_id") == eid]
    mem = _sort_created_desc(mem, key="reserved_at")[:lim]

    if db_rows is not None and len(db_rows) == 0 and not mem:
        source = "empty"
        deliveries: list[dict[str, Any]] = []
    elif mem:
        source = "memory"
        deliveries = mem
    else:
        source = "empty"
        deliveries = []

    return {
        "ok": True,
        "deliveries": deliveries,
        "total": len(deliveries),
        "source": source,
        "filters": {"event_id": eid},
    }


def list_subjects(limit: int = 50) -> dict[str, Any]:
    """List subject/thread projections."""
    lim = max(1, min(int(limit or 50), 200))

    db_rows = _db_list_subjects(limit=lim)
    if db_rows is not None and len(db_rows) > 0:
        return {
            "ok": True,
            "subjects": db_rows[:lim],
            "total": len(db_rows),
            "source": "db",
        }

    mem = _sort_created_desc(_memory_subjects(), key="last_activity_at")[:lim]
    if db_rows is not None and len(db_rows) == 0 and not mem:
        source = "empty"
        subjects: list[dict[str, Any]] = []
    elif mem:
        source = "memory"
        subjects = mem
    else:
        source = "empty"
        subjects = []

    return {
        "ok": True,
        "subjects": subjects,
        "total": len(subjects),
        "source": source,
    }


def health() -> dict[str, Any]:
    """Ledger health for the communications workspace banner."""
    try:
        from scripts.lib.comms.mode import get_gateway_mode, mode_diagnostics
    except Exception:
        from lib.comms.mode import get_gateway_mode, mode_diagnostics  # type: ignore

    mode = get_gateway_mode(refresh=True)
    diag = mode_diagnostics(refresh=True)
    events = list_events(limit=1)
    deliveries = list_deliveries(limit=1)
    subjects = list_subjects(limit=1)

    ledger_source = events.get("source") or "empty"
    db_reachable = _events_db_conn() is not None
    delivery_owned = False  # Phase 7: gateway never owns delivery while OFF/SHADOW

    return {
        "ok": True,
        "ledger": {
            "source": ledger_source,
            "db_reachable": db_reachable,
            "events_source": events.get("source"),
            "deliveries_source": deliveries.get("source"),
            "subjects_source": subjects.get("source"),
            "events_total_sample": events.get("total", 0),
            "deliveries_total_sample": deliveries.get("total", 0),
            "subjects_total_sample": subjects.get("total", 0),
        },
        "mode": mode,
        "mode_diagnostics": diag,
        "delivery_owned": delivery_owned,
        "banner": "Ledger-backed · gateway does not own delivery while OFF/SHADOW",
        "phase": 7,
    }
