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
    hub: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """List CommunicationEvent projections. Prefer DB; fall back to memory.

    With `hub` filters (q, category, priority, lifecycle_status, since/until, sort, offset …) the server-side hub
    query runs; it falls back to this legacy list when the hub columns are not migrated yet."""
    if hub:
        f = dict(hub, limit=limit, subject_key=subject_key)
        out = hub_events(f)
        if out is not None:
            return out
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


# ── Communications hub (operator 2026-10-07) ────────────────────────────────
# Server-side search / filter / sort / paging / facets over classified events; expired rows are hidden unless
# asked for. Columns from migrations/2026_10_07_communication_classification.sql; classification from
# scripts/lib/comms/classify.py; lifecycle by scripts/comms_lifecycle.py.

HUB_SORTS = {"created_at": "created_at", "priority_score": "priority_score", "confidence": "confidence",
             "risk_score": "risk_score", "reward_score": "reward_score", "time_sensitivity": "time_sensitivity",
             "expires_at": "expires_at", "actionable_since": "actionable_since",
             "priority": "CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"}
HUB_STATUSES = ("active", "acknowledged", "superseded", "expired")
REENTRY_STATUSES = ("opportunity", "potential", "confirmed", "expired", "invalidated")
_LIVE = ("status IN ('active', 'acknowledged') AND NOT (NOT legal_hold AND expires_at IS NOT NULL AND "
         "GREATEST(expires_at, COALESCE(retain_until, expires_at)) < now())")
HUB_ACTIONS = ("acknowledge", "unacknowledge", "retain", "release", "expire")


def _csv(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split(",") if x.strip()]


def hub_where(f: dict[str, Any], *, skip: tuple = ()) -> tuple[str, list[Any]]:
    """WHERE clause for the hub filters (pure; tested)."""
    clauses, params = ["1=1"], []
    statuses = [x for x in _csv(f.get("lifecycle_status")) if x in HUB_STATUSES]
    reentry = [x for x in _csv(f.get("reentry_status")) if x in REENTRY_STATUSES]
    if "lifecycle_status" not in skip:
        if statuses:
            clauses.append("status = ANY(%s)")
            params.append(statuses)
        elif not f.get("include_expired") and not ({"expired", "invalidated"} & set(reentry)):
            clauses.append(_LIVE)                     # active views never show expired or superseded items
    if reentry and "reentry_status" not in skip:
        clauses.append("reentry_status = ANY(%s)")
        params.append(reentry)
    syms = [x.upper() for x in _csv(f.get("symbol"))]
    if syms:
        clauses.append("symbols && %s::text[]")
        params.append(syms)
    if str(f.get("actionable") or "").lower() in ("1", "true", "yes"):
        clauses.append("actionable")
    for key, col in (("min_confidence", "confidence"), ("min_risk", "risk_score"), ("min_reward", "reward_score"),
                     ("min_time", "time_sensitivity")):
        if f.get(key) not in (None, ""):
            clauses.append(f"{col} >= %s")
            params.append(float(f[key]))
    if f.get("expiring_within_h") not in (None, ""):
        clauses.append("expires_at <= now() + make_interval(hours => %s)")
        params.append(float(f["expiring_within_h"]))
    for key, col in (("category", "category"), ("priority", "priority"), ("severity", "severity"),
                     ("direction", "direction"), ("message_class", "message_class"), ("producer", "producer")):
        vals = _csv(f.get(key))
        if vals and key not in skip:
            clauses.append(f"{col} = ANY(%s)")
            params.append([v.upper() for v in vals] if key == "direction" else vals)
    if f.get("subject_key"):
        clauses.append("subject_key = %s")
        params.append(str(f["subject_key"]))
    if f.get("since"):
        clauses.append("created_at >= %s")
        params.append(str(f["since"]))
    if f.get("until"):
        clauses.append("created_at <= %s")
        params.append(str(f["until"]))
    if f.get("min_score") not in (None, ""):
        clauses.append("priority_score >= %s")
        params.append(float(f["min_score"]))
    q = str(f.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append("(short_summary ILIKE %s OR sanitized_body ILIKE %s OR subject_key ILIKE %s "
                       "OR producer ILIKE %s OR COALESCE(incident_id,'') ILIKE %s OR event_id = %s)")
        params.extend([like, like, like, like, like, q])
    return " AND ".join(clauses), params


_HUB_COLS = """event_id, schema_version, direction, event_type, message_class, severity, audience, producer,
    subject_key, thread_id, correlation_id, incident_id, curation_mode, retention_class, knowledge_status,
    knowledge_eligibility, short_summary, sanitized_body, created_at, observed_at, gateway_mode_at_write,
    entity_refs, protected_facts, provider_coordinates, delivery_policy, idempotency_key,
    category, priority, priority_score, confidence, risk_score, reward_score, time_sensitivity, reentry_status,
    actionable, actionable_since, action_hint, symbols, classified_by, status AS lifecycle_status, superseded_by,
    acknowledged_at, acknowledged_by, retain_until, retained_by, legal_hold, expires_at"""


def _headline(body: str) -> str:
    try:
        from scripts.lib.comms.classify import headline
        return headline(body)
    except Exception:
        return (body or "")[:160]


def _project_hub(row: dict[str, Any]) -> dict[str, Any]:
    out = _project_event(row, source="db")
    exp = row.get("expires_at")
    ru = row.get("retain_until")
    eff = max([x for x in (exp, ru) if x is not None], default=None)
    left = None
    if eff is not None and not row.get("legal_hold"):
        from datetime import datetime as _dt, timezone as _tz
        left = int((eff - _dt.now(_tz.utc)).total_seconds())
    def _n(k: str):
        return float(row[k]) if row.get(k) is not None else None

    out.update({
        "category": row.get("category"), "priority": row.get("priority"),
        "priority_score": _n("priority_score"), "confidence": _n("confidence"), "risk_score": _n("risk_score"),
        "reward_score": _n("reward_score"), "time_sensitivity": _n("time_sensitivity"),
        "reentry_status": row.get("reentry_status"), "actionable": bool(row.get("actionable")),
        "actionable_since": _iso(row.get("actionable_since")), "action_hint": row.get("action_hint"),
        "symbols": list(row.get("symbols") or []), "superseded_by": row.get("superseded_by"),
        "headline": _headline(row.get("sanitized_body") or row.get("short_summary") or ""),
        "classified_by": row.get("classified_by"), "lifecycle_status": row.get("lifecycle_status"),
        "acknowledged_at": _iso(row.get("acknowledged_at")), "acknowledged_by": row.get("acknowledged_by"),
        "retain_until": _iso(ru), "retained_by": row.get("retained_by"), "legal_hold": bool(row.get("legal_hold")),
        "expires_at": _iso(exp), "ttl_remaining_s": left,
    })
    return out


_PROJ_CACHE: dict[str, Any] = {"mtime": None, "items": {}}


def _opportunity_items() -> dict[str, Any]:
    """CIO opportunity projection (entry zone / targets / conviction), cached by mtime."""
    try:
        try:
            from scripts.lib.cio_opportunity_store import PROJECTION_PATH
        except ImportError:  # pragma: no cover
            from lib.cio_opportunity_store import PROJECTION_PATH  # type: ignore
        m = PROJECTION_PATH.stat().st_mtime
        if _PROJ_CACHE["mtime"] != m:
            _PROJ_CACHE["items"] = (json.loads(PROJECTION_PATH.read_text(encoding="utf-8")).get("items") or {})
            _PROJ_CACHE["mtime"] = m
    except Exception:
        return {}
    return _PROJ_CACHE["items"]


def attach_market(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Operator 2026-10-08 ("why no prices"): every item that names a ticker carries the data-broker quote read
    NOW (AGENTS §7A — price is the broker quote at read time) and, where the CIO has them, the entry zone and
    target. Read-only; an unavailable quote stays absent (never a stale number presented as current)."""
    syms = sorted({(e.get("symbols") or [None])[0] for e in events if (e.get("symbols") or [None])[0]})
    if not syms:
        return events
    try:
        from db_adapter import _execute
        from lib.data_broker.market_quote import get_price_batch

        quotes = get_price_batch(lambda sql, params=None, fetch="all": _execute(sql, params, fetch=fetch),
                                 syms, skip_live=True) or {}
    except Exception:
        quotes = {}
    opp = _opportunity_items()
    for e in events:
        sym = (e.get("symbols") or [None])[0]
        if not sym:
            continue
        q = quotes.get(sym) or {}
        if q.get("price") is not None:
            e["market"] = {"symbol": sym, "price": q.get("price"), "day_change_pct": q.get("chg_pct"),
                           "source": q.get("source"), "as_of": q.get("as_of") or q.get("fetched_at")}
        a = opp.get(sym) or {}
        rr = a.get("risk_reward") or {}
        if rr.get("entry_zone") or rr.get("primary_target") or rr.get("targets"):
            e["levels"] = {"entry_zone": rr.get("entry_zone"), "entry_ref": rr.get("entry_ref"),
                           "invalidation_level": rr.get("invalidation_level"),
                           "target": rr.get("primary_target") or ((rr.get("targets") or [{}])[0]).get("px"),
                           "rr": rr.get("rr"), "conviction": a.get("conviction"), "rank": a.get("rank")}
    return events


def hub_events(filters: dict[str, Any]) -> dict[str, Any] | None:
    """Hub list + total + facets, or None when the DB / hub columns are unavailable."""
    conn = _events_db_conn()
    if conn is None:
        return None
    lim = max(1, min(int(filters.get("limit") or 100), 500))
    off = max(0, int(filters.get("offset") or 0))
    sort = HUB_SORTS.get(str(filters.get("sort") or "created_at"), "created_at")
    order = "ASC" if str(filters.get("order") or "desc").lower() == "asc" else "DESC"
    where, params = hub_where(filters)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_HUB_COLS} FROM communication_events WHERE {where} "
                        f"ORDER BY {sort} {order} NULLS LAST, created_at DESC LIMIT %s OFFSET %s",
                        params + [lim, off])
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.execute(f"SELECT count(*) FROM communication_events WHERE {where}", params)
            total = cur.fetchone()[0]
            facets: dict[str, dict[str, int]] = {}
            for dim in ("category", "priority"):
                w, p = hub_where(filters, skip=(dim,))
                cur.execute(f"SELECT {dim}, count(*) FROM communication_events WHERE {w} GROUP BY 1", p)
                facets[dim] = {str(k): n for k, n in cur.fetchall()}
            w, p = hub_where(filters, skip=("lifecycle_status",))
            cur.execute(f"SELECT status, count(*) FROM communication_events WHERE {w} GROUP BY 1", p)
            facets["lifecycle_status"] = {str(k): n for k, n in cur.fetchall()}
            w, p = hub_where(dict(filters, include_expired=True), skip=("reentry_status",))
            cur.execute(f"SELECT reentry_status, count(*) FROM communication_events WHERE {w} "
                        "AND category = 're_entry' GROUP BY 1", p)
            facets["reentry_status"] = {str(k): n for k, n in cur.fetchall()}
        conn.rollback()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    try:
        from scripts.lib.comms.classify import categories as _cats
        cats = _cats()
    except Exception:
        cats = []
    return {"ok": True, "events": attach_market([_project_hub(r) for r in rows]), "total": total, "limit": lim, "offset": off,
            "source": "db", "hub": True, "facets": facets, "categories": cats,
            "priorities": ["critical", "high", "medium", "low"], "statuses": list(HUB_STATUSES),
            "reentry_statuses": list(REENTRY_STATUSES), "sorts": list(HUB_SORTS),
            "filters": {k: v for k, v in filters.items() if v not in (None, "", [])}}


# The six questions the operator asks on opening Communications (2026-10-07).
BOARD_PANELS = {
    "attention": ("Needs attention now", "actionable AND priority IN ('critical','high')",
                  "CASE priority WHEN 'critical' THEN 0 ELSE 1 END, priority_score DESC"),
    "reward": ("Highest-reward opportunities",
               "actionable AND category IN ('reward','high_conviction_opportunity','re_entry')",
               "reward_score DESC, confidence DESC"),
    "reentry": ("Re-entry candidates", "category = 're_entry' AND reentry_status IN ('confirmed','opportunity','potential')",
                "CASE reentry_status WHEN 'confirmed' THEN 0 WHEN 'opportunity' THEN 1 ELSE 2 END, priority_score DESC"),
    "risk": ("Highest risk", "(category IN ('threat','risk') OR risk_score >= 0.6)",
             "risk_score DESC, time_sensitivity DESC"),
    "expiring": ("Expiring soon", "actionable AND expires_at <= now() + interval '12 hours'", "expires_at ASC"),
    "recent": ("Recently actionable", "actionable AND actionable_since >= now() - interval '24 hours'",
               "actionable_since DESC"),
}


def board(limit: int = 6) -> dict[str, Any] | None:
    """Top items per decision panel, live items only; None when the DB / hub columns are unavailable."""
    conn = _events_db_conn()
    if conn is None:
        return None
    lim = max(1, min(int(limit or 6), 25))
    panels: dict[str, Any] = {}
    try:
        with conn.cursor() as cur:
            for key, (label, cond, order) in BOARD_PANELS.items():
                cur.execute(f"SELECT {_HUB_COLS} FROM communication_events WHERE {_LIVE} AND {cond} "
                            f"ORDER BY {order} NULLS LAST, created_at DESC LIMIT %s", (lim,))
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                cur.execute(f"SELECT count(*) FROM communication_events WHERE {_LIVE} AND {cond}")
                panels[key] = {"label": label, "count": cur.fetchone()[0], "items": attach_market([_project_hub(r) for r in rows])}
            cur.execute(f"SELECT count(*), count(*) FILTER (WHERE actionable) FROM communication_events WHERE {_LIVE}")
            live, actionable = cur.fetchone()
        conn.rollback()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    return {"ok": True, "panels": panels, "live": live, "actionable": actionable,
            "ignorable": live - actionable, "source": "db"}


def bulk_sql(action: str, retain_hours: float | None = None) -> tuple[str, list[Any]]:
    """UPDATE for one bulk action (pure; tested). %s placeholders: [*extra, actor, ids]."""
    if action == "acknowledge":
        return ("UPDATE communication_events SET status='acknowledged', acknowledged_at=now(), acknowledged_by=%s "
                "WHERE event_id = ANY(%s) AND status <> 'expired'"), []
    if action == "unacknowledge":
        return ("UPDATE communication_events SET status='active', acknowledged_at=NULL, acknowledged_by=%s "
                "WHERE event_id = ANY(%s) AND status = 'acknowledged'"), []
    if action == "retain":
        if not retain_hours:
            return ("UPDATE communication_events SET legal_hold=TRUE, retained_by=%s, "
                    "status = CASE WHEN status='expired' THEN 'active' ELSE status END WHERE event_id = ANY(%s)"), []
        return ("UPDATE communication_events SET retain_until = now() + make_interval(hours => %s), retained_by=%s, "
                "status = CASE WHEN status='expired' THEN 'active' ELSE status END WHERE event_id = ANY(%s)"), \
            [float(retain_hours)]
    if action == "release":
        return ("UPDATE communication_events SET legal_hold=FALSE, retain_until=NULL, retained_by=%s "
                "WHERE event_id = ANY(%s)"), []
    if action == "expire":
        return ("UPDATE communication_events SET status='expired', expires_at=LEAST(COALESCE(expires_at, now()), now()), "
                "legal_hold=FALSE, retain_until=NULL, retained_by=%s WHERE event_id = ANY(%s)"), []
    raise ValueError(f"unknown action {action!r}; expected one of {HUB_ACTIONS}")


def bulk_apply(ids: list[str], action: str, actor: str, retain_hours: float | None = None) -> int:
    sql, extra = bulk_sql(action, retain_hours)
    conn = _events_db_conn()
    if conn is None:
        raise RuntimeError("communications DB unavailable")
    with conn.cursor() as cur:
        cur.execute(sql, extra + [actor, list(ids)])
        n = cur.rowcount
    conn.commit()
    return n


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


def list_agent_consumption(
    agent_id: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Read-only agent consumption projection (Wave E).

    Returns subscriptions + consumption receipts so the Command Center Agent
    Memory view can show which CIO/Advisory/Hermes agents consumed which events
    and what they derived. Never writes, never calls providers.
    """
    lim = max(1, min(int(limit or 200), 1000))
    aid = (agent_id or "").strip() or None
    try:
        from scripts.lib.comms.agent_contracts import (  # noqa: F401
            list_consumption_receipts,
            list_subscriptions,
        )
    except Exception:
        try:
            from lib.comms.agent_contracts import (  # noqa: F401
                list_consumption_receipts,
                list_subscriptions,
            )
        except Exception:
            return {
                "ok": True,
                "subscriptions": [],
                "receipts": [],
                "total_receipts": 0,
                "total_subscriptions": 0,
                "source": "empty",
                "note": "agent_contracts unavailable",
            }

    subscriptions = list_subscriptions(aid) if aid else list_subscriptions(None)
    receipts = list_consumption_receipts(aid, limit=lim)

    def _iso(v: Any) -> str | None:
        if v is None:
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    subs = [
        {
            "subscription_id": s.get("subscription_id"),
            "agent_id": s.get("agent_id"),
            "agent_version": s.get("agent_version"),
            "filter": s.get("filter"),
            "enabled": s.get("enabled"),
            "created_at": _iso(s.get("created_at")),
            "persisted": s.get("persisted") or "memory",
        }
        for s in subscriptions
    ]
    recs = [
        {
            "receipt_id": r.get("receipt_id"),
            "agent_id": r.get("agent_id"),
            "agent_version": r.get("agent_version"),
            "event_id": r.get("event_id"),
            "thread_id": r.get("thread_id"),
            "purpose": r.get("purpose"),
            "policy_decision": r.get("policy_decision"),
            "retrieved_at": _iso(r.get("retrieved_at")),
            "acknowledged_at": _iso(r.get("acknowledged_at")),
            "derived_artifact_ids": r.get("derived_artifact_ids") or [],
            "influence_declaration": r.get("influence_declaration"),
            "influence_event_ids": r.get("influence_event_ids") or [],
            "persisted": r.get("persisted") or "memory",
        }
        for r in receipts
    ]

    return {
        "ok": True,
        "subscriptions": subs,
        "receipts": recs,
        "total_receipts": len(recs),
        "total_subscriptions": len(subs),
        "source": "db" if any(r.get("persisted") == "db" for r in recs) else ("memory" if recs else "empty"),
        "filters": {"agent_id": aid},
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

    # Derive ownership from the same allowlist delivery uses (fail-closed).
    # Import channel_adapters as a module alias to avoid provider-ban false positives.
    try:
        from scripts.lib.comms import channel_adapters as _comms_adapters
    except Exception:
        from lib.comms import channel_adapters as _comms_adapters  # type: ignore

    owned_classes = list(_comms_adapters.telegram_owned_classes(mode))
    delivery_owned = mode in ("CANARY", "ACTIVE") and bool(owned_classes)
    if mode in ("OFF", "SHADOW"):
        banner = "Ledger-backed · gateway does not own delivery while OFF/SHADOW"
    elif delivery_owned:
        banner = (
            f"Ledger-backed · gateway owns Telegram classes: "
            f"{', '.join(owned_classes)}"
        )
    else:
        banner = (
            f"Ledger-backed · mode {mode} but no Telegram class allowlist "
            f"(deliver fail-closed)"
        )

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
        "owned_classes": owned_classes,
        "banner": banner,
        "phase": 7,
    }
