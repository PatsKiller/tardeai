"""Subject Memory / SubjectThread@v1 — cross-channel subject history.

Answers "What happened previously on this exact subject?" before curation.
Policy-eligible retrieval only when eligible_only=True.
Distinct from cio_rehydrate instrument cognition.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

SUBJECT_DOMAINS = frozenset(
    {
        "symbol",
        "account",
        "incident",
        "proposal",
        "research",
        "system",
        "operator",
    }
)

# Single-part shorthand: domain:<value> when the kwarg matches this name.
_PRIMARY_PART = {
    "symbol": "symbol",
    "account": "account_id",
    "incident": "incident_id",
    "proposal": "proposal_id",
    "research": "research_id",
    "system": "component",
    "operator": "topic",
}

# knowledge_eligibility values treated as ineligible for policy retrieval.
_INELIGIBLE = frozenset({"", "ineligible", "none", "denied", "blocked"})

_SUMMARY_CURATION = frozenset({"LLM_SUMMARY", "TEMPLATE"})

# In-process fallback when DB / tables unavailable (mirrors client.py).
_SUBJECTS: dict[str, dict[str, Any]] = {}
_MEMBERSHIP: list[dict[str, Any]] = []  # rows keyed by (subject_key, event_id) uniqueness
_lock = threading.Lock()


def subject_key_for(domain: str, **parts: Any) -> str:
    """Deterministic subject key for a domain + identifying parts.

    Examples:
      subject_key_for("symbol", symbol="AAPL") -> "symbol:AAPL"
      subject_key_for("system", component="watchdog") -> "system:watchdog"
      subject_key_for("incident", incident_id="inc1", account_id="a") ->
          "incident:account_id=a:incident_id=inc1"
    """
    d = (domain or "").strip().lower()
    if d not in SUBJECT_DOMAINS:
        raise ValueError(f"invalid subject domain: {domain!r}")
    cleaned: dict[str, str] = {}
    for k, v in parts.items():
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        if d == "symbol" and k in ("symbol", "ticker"):
            s = s.upper()
        cleaned[str(k).strip()] = s
    if not cleaned:
        raise ValueError("subject_key_for requires at least one non-empty part")

    primary = _PRIMARY_PART.get(d)
    if len(cleaned) == 1:
        k, v = next(iter(cleaned.items()))
        if k == primary or k == d or (d == "symbol" and k == "ticker"):
            return f"{d}:{v}"

    segments = [f"{k}={cleaned[k]}" for k in sorted(cleaned.keys())]
    return f"{d}:" + ":".join(segments)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db_conn():
    """Best-effort connection; None when unavailable or subject tables missing."""
    try:
        from db_adapter import _get_conn  # scripts/ on path in many entrypoints
    except Exception:
        try:
            from scripts.db_adapter import _get_conn  # type: ignore
        except Exception:
            return None
    try:
        conn = _get_conn()
    except Exception:
        return None
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                 WHERE table_name IN (
                     'communication_subjects', 'communication_thread_membership'
                 )
                """
            )
            n = cur.fetchone()[0]
        if int(n) < 2:
            return None
    except Exception:
        return None
    return conn


def _domain_from_subject_key(subject_key: str) -> str:
    head = (subject_key or "").split(":", 1)[0].strip().lower()
    if head in SUBJECT_DOMAINS:
        return head
    return "system"


def upsert_subject(
    subject_key: str,
    *,
    domain: str | None = None,
    canonical_entities: dict[str, Any] | None = None,
    aliases: list[Any] | None = None,
    latest_state: dict[str, Any] | None = None,
    open_questions: list[Any] | None = None,
    operator_decisions: list[Any] | None = None,
    outcomes: list[Any] | None = None,
    activity_at: datetime | None = None,
) -> dict[str, Any]:
    """Create or update a subject row. Returns the subject dict."""
    if not subject_key or not str(subject_key).strip():
        raise ValueError("subject_key required")
    sk = str(subject_key).strip()
    dom = (domain or _domain_from_subject_key(sk)).strip().lower()
    if dom not in SUBJECT_DOMAINS:
        raise ValueError(f"invalid subject domain: {dom!r}")
    when = activity_at or _now()
    entities = canonical_entities if canonical_entities is not None else {}
    alias_list = aliases if aliases is not None else []
    state = latest_state if latest_state is not None else {}
    questions = open_questions if open_questions is not None else []
    decisions = operator_decisions if operator_decisions is not None else []
    outs = outcomes if outcomes is not None else []

    conn = _db_conn()
    if conn is not None:
        try:
            return _upsert_subject_db(
                conn,
                sk,
                domain=dom,
                canonical_entities=entities,
                aliases=alias_list,
                latest_state=state,
                open_questions=questions,
                operator_decisions=decisions,
                outcomes=outs,
                activity_at=when,
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            # Fall through to memory.

    return _upsert_subject_memory(
        sk,
        domain=dom,
        canonical_entities=entities,
        aliases=alias_list,
        latest_state=state,
        open_questions=questions,
        operator_decisions=decisions,
        outcomes=outs,
        activity_at=when,
    )


def _upsert_subject_memory(
    subject_key: str,
    *,
    domain: str,
    canonical_entities: dict[str, Any],
    aliases: list[Any],
    latest_state: dict[str, Any],
    open_questions: list[Any],
    operator_decisions: list[Any],
    outcomes: list[Any],
    activity_at: datetime,
) -> dict[str, Any]:
    with _lock:
        existing = _SUBJECTS.get(subject_key)
        if existing is None:
            row = {
                "subject_key": subject_key,
                "domain": domain,
                "canonical_entities": dict(canonical_entities),
                "aliases": list(aliases),
                "first_activity_at": activity_at,
                "last_activity_at": activity_at,
                "latest_state": dict(latest_state),
                "open_questions": list(open_questions),
                "operator_decisions": list(operator_decisions),
                "outcomes": list(outcomes),
                "persisted": "memory",
            }
            _SUBJECTS[subject_key] = row
            return dict(row)
        existing["last_activity_at"] = activity_at
        if canonical_entities:
            merged = dict(existing.get("canonical_entities") or {})
            merged.update(canonical_entities)
            existing["canonical_entities"] = merged
        if aliases:
            seen = list(existing.get("aliases") or [])
            for a in aliases:
                if a not in seen:
                    seen.append(a)
            existing["aliases"] = seen
        if latest_state:
            merged_state = dict(existing.get("latest_state") or {})
            merged_state.update(latest_state)
            existing["latest_state"] = merged_state
        if open_questions:
            existing["open_questions"] = list(open_questions)
        if operator_decisions:
            existing["operator_decisions"] = list(operator_decisions)
        if outcomes:
            existing["outcomes"] = list(outcomes)
        existing["persisted"] = "memory"
        return dict(existing)


def _upsert_subject_db(
    conn,
    subject_key: str,
    *,
    domain: str,
    canonical_entities: dict[str, Any],
    aliases: list[Any],
    latest_state: dict[str, Any],
    open_questions: list[Any],
    operator_decisions: list[Any],
    outcomes: list[Any],
    activity_at: datetime,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO communication_subjects (
                subject_key, domain, canonical_entities, aliases,
                first_activity_at, last_activity_at, latest_state,
                open_questions, operator_decisions, outcomes
            ) VALUES (
                %s, %s, %s::jsonb, %s::jsonb,
                %s, %s, %s::jsonb,
                %s::jsonb, %s::jsonb, %s::jsonb
            )
            ON CONFLICT (subject_key) DO UPDATE SET
                last_activity_at = GREATEST(
                    communication_subjects.last_activity_at, EXCLUDED.last_activity_at
                ),
                canonical_entities = CASE
                    WHEN EXCLUDED.canonical_entities = '{}'::jsonb
                    THEN communication_subjects.canonical_entities
                    ELSE communication_subjects.canonical_entities || EXCLUDED.canonical_entities
                END,
                aliases = CASE
                    WHEN EXCLUDED.aliases = '[]'::jsonb
                    THEN communication_subjects.aliases
                    ELSE EXCLUDED.aliases
                END,
                latest_state = CASE
                    WHEN EXCLUDED.latest_state = '{}'::jsonb
                    THEN communication_subjects.latest_state
                    ELSE communication_subjects.latest_state || EXCLUDED.latest_state
                END,
                open_questions = CASE
                    WHEN EXCLUDED.open_questions = '[]'::jsonb
                    THEN communication_subjects.open_questions
                    ELSE EXCLUDED.open_questions
                END,
                operator_decisions = CASE
                    WHEN EXCLUDED.operator_decisions = '[]'::jsonb
                    THEN communication_subjects.operator_decisions
                    ELSE EXCLUDED.operator_decisions
                END,
                outcomes = CASE
                    WHEN EXCLUDED.outcomes = '[]'::jsonb
                    THEN communication_subjects.outcomes
                    ELSE EXCLUDED.outcomes
                END
            RETURNING subject_key, domain, canonical_entities, aliases,
                      first_activity_at, last_activity_at, latest_state,
                      open_questions, operator_decisions, outcomes
            """,
            (
                subject_key,
                domain,
                json.dumps(canonical_entities),
                json.dumps(aliases),
                activity_at,
                activity_at,
                json.dumps(latest_state),
                json.dumps(open_questions),
                json.dumps(operator_decisions),
                json.dumps(outcomes),
            ),
        )
        row = cur.fetchone()
        conn.commit()
    cols = (
        "subject_key",
        "domain",
        "canonical_entities",
        "aliases",
        "first_activity_at",
        "last_activity_at",
        "latest_state",
        "open_questions",
        "operator_decisions",
        "outcomes",
    )
    out = dict(zip(cols, row))
    out["persisted"] = "db"
    return out


def attach_event_to_subject(
    subject_key: str,
    event_id: str,
    channel: str | None = None,
    provider_coordinates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record cross-channel membership of an event under a subject.

    Ensures the subject row exists (minimal upsert). Idempotent on
    (subject_key, event_id).
    """
    if not subject_key or not str(subject_key).strip():
        raise ValueError("subject_key required")
    if not event_id or not str(event_id).strip():
        raise ValueError("event_id required")
    sk = str(subject_key).strip()
    eid = str(event_id).strip()
    coords = provider_coordinates or {}
    when = _now()

    # Ensure subject exists (memory or DB).
    upsert_subject(sk, activity_at=when)

    conn = _db_conn()
    if conn is not None:
        try:
            return _attach_db(conn, sk, eid, channel=channel, coords=coords, when=when)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    return _attach_memory(sk, eid, channel=channel, coords=coords, when=when)


def _attach_memory(
    subject_key: str,
    event_id: str,
    *,
    channel: str | None,
    coords: dict[str, Any],
    when: datetime,
) -> dict[str, Any]:
    with _lock:
        for row in _MEMBERSHIP:
            if row["subject_key"] == subject_key and row["event_id"] == event_id:
                return dict(row)
        row = {
            "subject_key": subject_key,
            "event_id": event_id,
            "channel": channel,
            "provider_coordinates": dict(coords),
            "joined_at": when,
            "persisted": "memory",
        }
        _MEMBERSHIP.append(row)
        sub = _SUBJECTS.get(subject_key)
        if sub is not None:
            sub["last_activity_at"] = when
        return dict(row)


def _attach_db(
    conn,
    subject_key: str,
    event_id: str,
    *,
    channel: str | None,
    coords: dict[str, Any],
    when: datetime,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO communication_thread_membership (
                subject_key, event_id, channel, provider_coordinates, joined_at
            ) VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (subject_key, event_id) DO UPDATE SET
                channel = COALESCE(EXCLUDED.channel, communication_thread_membership.channel),
                provider_coordinates = CASE
                    WHEN EXCLUDED.provider_coordinates = '{}'::jsonb
                    THEN communication_thread_membership.provider_coordinates
                    ELSE EXCLUDED.provider_coordinates
                END
            RETURNING subject_key, event_id, channel, provider_coordinates, joined_at
            """,
            (subject_key, event_id, channel, json.dumps(coords), when),
        )
        row = cur.fetchone()
        cur.execute(
            """
            UPDATE communication_subjects
               SET last_activity_at = GREATEST(last_activity_at, %s)
             WHERE subject_key = %s
            """,
            (when, subject_key),
        )
        conn.commit()
    out = {
        "subject_key": row[0],
        "event_id": row[1],
        "channel": row[2],
        "provider_coordinates": row[3],
        "joined_at": row[4],
        "persisted": "db",
    }
    return out


def _is_eligible(eligibility: Any) -> bool:
    val = str(eligibility or "").strip().lower()
    return val not in _INELIGIBLE


def _artifact_kind(event_row: dict[str, Any]) -> str:
    curation = str(event_row.get("curation_mode") or "")
    if curation in _SUMMARY_CURATION:
        return "summary"
    if event_row.get("short_summary") and not event_row.get("sanitized_body"):
        return "summary"
    return "evidence"


def _event_from_memory(event_id: str) -> dict[str, Any] | None:
    try:
        from scripts.lib.comms.client import memory_store_snapshot
    except Exception:
        return None
    snap = memory_store_snapshot()
    row = snap.get(event_id)
    return dict(row) if row else None


def _events_table_available(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                 WHERE table_name = 'communication_events'
                """
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def retrieve_subject_history(
    subject_key: str,
    *,
    limit: int = 50,
    eligible_only: bool = True,
) -> list[dict[str, Any]]:
    """Return policy-eligible (by default) events for a subject.

    Sources: in-memory membership + ledger memory store, and/or DB when
    communication_events / membership tables exist.

    Each item includes artifact_kind: 'evidence' | 'summary'.
    """
    if not subject_key or not str(subject_key).strip():
        return []
    sk = str(subject_key).strip()
    lim = max(1, int(limit))

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    conn = _db_conn()
    if conn is not None:
        try:
            db_rows = _retrieve_db(conn, sk, limit=lim, eligible_only=eligible_only)
            for r in db_rows:
                eid = str(r.get("event_id") or "")
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    rows.append(r)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    mem_rows = _retrieve_memory(sk, limit=lim, eligible_only=eligible_only)
    for r in mem_rows:
        eid = str(r.get("event_id") or "")
        if eid and eid not in seen_ids:
            seen_ids.add(eid)
            rows.append(r)

    def _sort_key(item: dict[str, Any]) -> Any:
        return item.get("joined_at") or item.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)

    rows.sort(key=_sort_key, reverse=True)
    return rows[:lim]


def _retrieve_memory(
    subject_key: str,
    *,
    limit: int,
    eligible_only: bool,
) -> list[dict[str, Any]]:
    with _lock:
        memberships = [dict(m) for m in _MEMBERSHIP if m["subject_key"] == subject_key]
    memberships.sort(key=lambda m: m.get("joined_at") or _now(), reverse=True)

    out: list[dict[str, Any]] = []
    for m in memberships:
        if len(out) >= limit:
            break
        ev = _event_from_memory(m["event_id"])
        if ev is None:
            # Membership without ledger body — still surface as evidence stub.
            item = {
                "event_id": m["event_id"],
                "subject_key": subject_key,
                "channel": m.get("channel"),
                "provider_coordinates": m.get("provider_coordinates") or {},
                "joined_at": m.get("joined_at"),
                "knowledge_eligibility": "unknown",
                "artifact_kind": "evidence",
                "source": "memory_membership",
            }
            if eligible_only:
                continue
            out.append(item)
            continue
        eligibility = ev.get("knowledge_eligibility", "ineligible")
        if eligible_only and not _is_eligible(eligibility):
            continue
        channel = m.get("channel")
        if not channel:
            chans = ev.get("channels")
            if isinstance(chans, list) and chans:
                channel = chans[0]
        item = {
            **ev,
            "channel": channel,
            "joined_at": m.get("joined_at"),
            "artifact_kind": _artifact_kind(ev),
            "source": "memory",
        }
        out.append(item)
    return out


def _retrieve_db(
    conn,
    subject_key: str,
    *,
    limit: int,
    eligible_only: bool,
) -> list[dict[str, Any]]:
    has_events = _events_table_available(conn)
    with conn.cursor() as cur:
        if has_events:
            eligibility_clause = ""
            if eligible_only:
                eligibility_clause = (
                    " AND LOWER(COALESCE(e.knowledge_eligibility, 'ineligible')) "
                    "NOT IN ('', 'ineligible', 'none', 'denied', 'blocked')"
                )
            cur.execute(
                f"""
                SELECT m.event_id, m.channel, m.provider_coordinates, m.joined_at,
                       e.direction, e.event_type, e.message_class, e.producer,
                       e.subject_key, e.short_summary, e.sanitized_body,
                       e.curation_mode, e.knowledge_eligibility, e.knowledge_status,
                       e.created_at, e.protected_facts, e.entity_refs, e.payload
                  FROM communication_thread_membership m
                  JOIN communication_events e ON e.event_id = m.event_id
                 WHERE m.subject_key = %s
                 {eligibility_clause}
                 ORDER BY m.joined_at DESC
                 LIMIT %s
                """,
                (subject_key, limit),
            )
            cols = [
                "event_id",
                "channel",
                "provider_coordinates",
                "joined_at",
                "direction",
                "event_type",
                "message_class",
                "producer",
                "subject_key",
                "short_summary",
                "sanitized_body",
                "curation_mode",
                "knowledge_eligibility",
                "knowledge_status",
                "created_at",
                "protected_facts",
                "entity_refs",
                "payload",
            ]
            out: list[dict[str, Any]] = []
            for tup in cur.fetchall():
                row = dict(zip(cols, tup))
                row["artifact_kind"] = _artifact_kind(row)
                row["source"] = "db"
                out.append(row)
            return out

        # Membership only (no events table).
        cur.execute(
            """
            SELECT event_id, channel, provider_coordinates, joined_at
              FROM communication_thread_membership
             WHERE subject_key = %s
             ORDER BY joined_at DESC
             LIMIT %s
            """,
            (subject_key, limit),
        )
        out = []
        for event_id, channel, coords, joined_at in cur.fetchall():
            if eligible_only:
                # Without event rows we cannot prove eligibility.
                continue
            out.append(
                {
                    "event_id": event_id,
                    "channel": channel,
                    "provider_coordinates": coords or {},
                    "joined_at": joined_at,
                    "subject_key": subject_key,
                    "knowledge_eligibility": "unknown",
                    "artifact_kind": "evidence",
                    "source": "db_membership",
                }
            )
        return out


def get_subject(subject_key: str) -> dict[str, Any] | None:
    """Fetch subject metadata from DB or memory."""
    if not subject_key:
        return None
    sk = str(subject_key).strip()
    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT subject_key, domain, canonical_entities, aliases,
                           first_activity_at, last_activity_at, latest_state,
                           open_questions, operator_decisions, outcomes
                      FROM communication_subjects
                     WHERE subject_key = %s
                    """,
                    (sk,),
                )
                row = cur.fetchone()
            if row:
                cols = (
                    "subject_key",
                    "domain",
                    "canonical_entities",
                    "aliases",
                    "first_activity_at",
                    "last_activity_at",
                    "latest_state",
                    "open_questions",
                    "operator_decisions",
                    "outcomes",
                )
                out = dict(zip(cols, row))
                out["persisted"] = "db"
                return out
        except Exception:
            pass
    with _lock:
        row = _SUBJECTS.get(sk)
        return dict(row) if row else None


def memory_subject_snapshot() -> dict[str, Any]:
    """Test helper: subjects + membership copy."""
    with _lock:
        return {
            "subjects": {k: dict(v) for k, v in _SUBJECTS.items()},
            "membership": [dict(m) for m in _MEMBERSHIP],
        }


def reset_subject_memory() -> None:
    """Test helper."""
    with _lock:
        _SUBJECTS.clear()
        _MEMBERSHIP.clear()
