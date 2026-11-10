#!/usr/bin/env python3
"""Durable alert event/outbox pipeline for normalized operator notifications."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any

from alert_occurrence_store import record_occurrence
from alert_runtime_mode import get_mode
from operator_alert_policy_v2 import (
    APPROVALS_ONLY,
    APPROVAL_ALLOWLIST,
    CRITICAL_IMMEDIATE_TYPES,
    CRITICAL_OPERATIONS,
    PAPER_OR_CANDIDATE_TYPES,
    POLICY_VERSION,
    ROUTE_COMMAND_CENTER,
    ROUTE_DIGEST,
    ROUTE_IMMEDIATE,
    AlertEvent,
    alert_fingerprint,
    alert_id_for,
    classify_legacy_message,
    event_to_jsonable,
    expires_at_for,
    incident_id_for,
    render_operator_message,
    route_event,
)

_MEM_EVENTS: dict[str, dict[str, Any]] = {}
_MEM_DELIVERIES: list[dict[str, Any]] = []
_MEM_DIGEST: list[dict[str, Any]] = []

DEFAULT_PREFERENCES = {
    "live_order_2fa_required": ("OFF", "IMMEDIATE", True, "TRADING", 900, 300, 600, True),
    "live_session_2fa_required": ("OFF", "IMMEDIATE", True, "TRADING", 900, 300, 600, True),
    "protective_order_approval_required": ("OFF", "IMMEDIATE", True, "RISK", 900, 300, 600, True),
    "material_live_authorization_amendment_required": ("OFF", "IMMEDIATE", True, "TRADING", 900, 300, 600, True),
    "orphaned_stop": ("IMMEDIATE", "OFF", True, "RISK", 86400, 900, 1800, True),
    "position_unprotected": ("IMMEDIATE", "OFF", True, "RISK", 86400, 900, 1800, True),
    "protection_failure": ("IMMEDIATE", "OFF", True, "RISK", 86400, 900, 1800, True),
    "broker_auth_blocking": ("IMMEDIATE", "OFF", True, "OPS", 86400, 900, 1800, True),
    "partial_fill_protection_uncertain": ("IMMEDIATE", "OFF", True, "RISK", 86400, 900, 1800, True),
    "paper_proposal": ("OFF", "OFF", True, "TRADING", 604800, 3600, None, False),
    "paper_approval": ("OFF", "OFF", True, "TRADING", 604800, 3600, None, False),
    "proposal_blocked_or_rebuild": ("OFF", "OFF", True, "TRADING", 604800, 3600, None, False),
    "proposal_revalidated_or_cancelled": ("DIGEST", "OFF", True, "TRADING", 86400, 3600, None, False),
    "research_update": ("OFF", "OFF", True, "OPS", 604800, 3600, None, False),
    "scanner_candidate": ("OFF", "OFF", True, "TRADING", 14400, 3600, None, False),
    "stop_warning": ("DIGEST", "OFF", True, "RISK", 86400, 3600, None, False),
    "siem_without_trading_impact": ("DIGEST", "OFF", True, "OPS", 86400, 3600, None, False),
    "confluence_flip": ("DIGEST", "OFF", True, "OPS", 86400, 3600, None, False),
    "job_telemetry": ("OFF", "OFF", True, "OPS", 604800, 3600, None, False),
    "debug_or_success": ("OFF", "OFF", False, "OPS", 604800, 3600, None, False),
}


def _db():
    """Connection ONLY when the outbox migration is actually present.

    Returning a live connection to an unmigrated database made every write raise
    UndefinedTable, which callers converted into a bare False — silently dropping
    operator alerts. Capability is checked explicitly here so an unmigrated database
    degrades to the in-memory path (OFF/SHADOW) instead of erroring, while ACTIVE
    is gated separately by alert_runtime_mode.require_active_capability().
    """
    try:
        from alert_runtime_mode import missing_tables
        from db_adapter import _get_conn
        conn = _get_conn()
    except Exception:
        return None
    if conn is None:
        return None
    try:
        if missing_tables(conn):
            return None
    except Exception:
        return None
    return conn


def _json(payload: Any) -> str:
    return json.dumps(payload or {}, separators=(",", ":"), default=str)


def ensure_default_preferences() -> None:
    conn = _db()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for alert_type, vals in DEFAULT_PREFERENCES.items():
                cur.execute(
                    """
                    INSERT INTO operator_alert_preferences
                    (alert_type, general_telegram, approval_telegram, command_center,
                     digest_bucket, ttl_seconds, dedupe_window_seconds, escalate_after_seconds,
                     sound_enabled, policy_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(alert_type) DO NOTHING
                    """,
                    (alert_type, *vals, POLICY_VERSION),
                )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _delivery_fingerprint(message: str) -> str:
    norm = " ".join((message or "").split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def publish_legacy_message(message: str, *, source_producer: str = "legacy_send_telegram",
                           bypass_router: bool = False,
                           resolving: bool = False,
                           intent_priority: str | None = None,
                           legacy_delivered: bool | None = None) -> dict[str, Any]:
    """Publish one legacy message as an observation.

    ``resolving`` says this observation reports the condition ENDING, not
    starting. It must be supplied by the caller: the input here is raw message
    text and ``classify_legacy_message`` carries no recovery vocabulary, so a
    recovery send is indistinguishable from an alert send by inspection.

    Measured 2026-09-21: this was the one missing link. ``publish_event`` has
    accepted ``resolving`` since it was written and threads it to the occurrence
    store, which sets ``resolved_at``/``status='resolved'`` from the dedupe
    decision -- and ``alert_dedupe`` only ever sets ``is_resolution`` when its
    caller says so. But this function, the SOLE production entry point into that
    plane, called ``publish_event(event)`` bare. So every incident could open and
    none could ever close: 41 open, 41 distinct dedupe keys, 0 resolved, oldest
    2026-09-16.

    ``legacy_delivered`` is what the legacy sender OBSERVED for this message (True/False from
    ``telegram_alert._legacy_send``); None means the caller did not ask. It is what tells the occurrence store whether a
    CRITICAL decision the legacy path suppressed is still owed to the operator (LQ-20261107-1815).
    """
    event = classify_legacy_message(message, source_producer=source_producer)
    payload = dict(event.payload)
    payload["bypass_router_requested"] = bool(bypass_router)
    if intent_priority:
        # The sender's declared notification-intent priority (telegram_alert_router.route_intent), kept beside
        # the observation so the normalized plane can see what the producer asked for.
        payload["intent_priority"] = str(intent_priority)
    if legacy_delivered is not None:
        payload["legacy_delivered"] = bool(legacy_delivered)
    event = AlertEvent(**{**event.__dict__, "payload": payload})
    # Only a caller that observed the legacy outcome passes the kwarg, so every other caller keeps its exact
    # pre-LQ-1815 call shape (same rule as the intent kwargs above).
    if legacy_delivered is None:
        return publish_event(event, resolving=resolving)
    return publish_event(event, resolving=resolving, legacy_delivered=legacy_delivered)


def occurrence_alert_id(fingerprint: str, observed_at: datetime) -> str:
    """A DISTINCT alert_id per observation.

    alert_occurrences.alert_id is UNIQUE, and the same condition legitimately
    recurs — so an id derived from the fingerprint alone collides on the second
    occurrence. Keying on the observation instant keeps it unique while staying
    deterministic for a given observation, which is what makes the DB tests
    reproducible. Microseconds, because two sends of the same condition inside
    one second are two observations, not one.
    """
    ts = int((_aware_utc(observed_at)).timestamp() * 1_000_000)
    return f"al_{fingerprint[:20]}_{ts}"


def _aware_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def publish_event(event: AlertEvent, *, resolving: bool = False,
                  legacy_delivered: bool | None = None) -> dict[str, Any]:
    """Publish one observation through the occurrence model.

    Rewritten 2026-07-29. The previous version wrote a single row per fingerprint:

        INSERT INTO alert_notification_events (...) ON CONFLICT (fingerprint)
        DO UPDATE SET ..., duplicate_count = duplicate_count + 1

    Three defects, all from the module still targeting the FIRST-DRAFT schema:

      1. alert_notification_events is now a derived VIEW over incidents joined to
         occurrences. It is not insertable, so this raised UndefinedColumn on
         `entity_id` the moment the migration was applied. It had never run
         before that because the object did not exist and the code fell through
         to the in-memory path — which is why the tests were green against a
         fallback rather than against the schema.
      2. Keying on the fingerprint made it both the IDENTITY of a condition and
         its LIFETIME dedupe key: the first occurrence suppressed every later one
         forever, and each repeat OVERWROTE the stored payload, destroying the
         occurrence history the model exists to keep.
      3. The notify decision was inferred from whether the row was newly
         inserted, rather than from should_notify() against persisted prior
         state — so severity escalation, action-now-required, state-version
         change, escalation deadline and post-resolution recurrence were all
         invisible.

    The persistence layer for the occurrence model already existed —
    alert_occurrence_store.record_occurrence() — and this function simply never
    adopted it. It claims the open incident FOR UPDATE, runs should_notify()
    against real prior state, appends an immutable occurrence carrying the
    decision AND its inputs, updates the incident counters, and enqueues delivery
    or digest, all in one transaction. This is now a thin adapter over it.
    """
    decision = route_event(event)
    fingerprint = alert_fingerprint(event)
    incident_id = incident_id_for(event)
    observed_at = _aware_utc(event.created_at)
    alert_id = occurrence_alert_id(fingerprint, observed_at)
    expires_at = expires_at_for(event, decision)

    payload = event_to_jsonable(event)
    payload["routing"] = {
        "route_mode": decision.route_mode,
        "logical_destination": decision.logical_destination,
        "digest_bucket": decision.digest_bucket,
    }

    conn = _db()
    if conn is None:
        return _publish_memory(event, decision, alert_id, incident_id, fingerprint, expires_at, payload)

    try:
        result = record_occurrence(
            conn,
            incident_id=incident_id,
            alert_id=alert_id,
            dedupe_key=fingerprint,
            event=event,
            route=decision,
            observed_at=observed_at,
            # No correlation key: the schema supports batching sibling
            # observations from one account/detection cycle into a single
            # incident, but nothing in the tree derives such a key today.
            # Passing None keeps each condition its own incident, which is the
            # honest behaviour until a producer supplies one. Inventing a key
            # here would silently merge unrelated conditions.
            correlation_key=None,
            resolving=resolving,
            runtime_mode=get_mode(),
            legacy_delivered=legacy_delivered,
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    # Preserve this function's published contract for existing callers.
    return {
        "ok": True,
        "alert_id": result["alert_id"],
        "incident_id": result["incident_id"],
        "occurrence_id": result.get("occurrence_id"),
        "fingerprint": fingerprint,
        "route_mode": decision.route_mode,
        "logical_destination": decision.logical_destination,
        "digest_bucket": decision.digest_bucket,
        "send_immediate": bool(result.get("queued")) and decision.route_mode == ROUTE_IMMEDIATE,
        "suppression_reason": result.get("suppression_reason"),
        "policy_version": decision.policy_version,
        "decision": result.get("decision"),
        "material_transition": result.get("material_transition"),
    }


def _publish_memory(event, decision, alert_id, incident_id, fingerprint, expires_at, payload):
    inserted = fingerprint not in _MEM_EVENTS
    if inserted:
        _MEM_EVENTS[fingerprint] = {
            "alert_id": alert_id,
            "event": event,
            "decision": decision,
            "incident_id": incident_id,
            "expires_at": expires_at,
            "payload": payload,
            "duplicate_count": 0,
        }
    else:
        _MEM_EVENTS[fingerprint]["duplicate_count"] += 1
    if decision.route_mode == ROUTE_DIGEST and decision.digest_bucket and inserted:
        _MEM_DIGEST.append({"alert_id": alert_id, "bucket": decision.digest_bucket, "event": event})
    _MEM_DELIVERIES.append({
        "alert_id": alert_id,
        "route_mode": decision.route_mode,
        "logical_destination": decision.logical_destination,
        "status": "queued" if inserted else "suppressed",
        "reason": "new_incident" if inserted else "duplicate_within_fingerprint",
    })
    return {
        "ok": True,
        "alert_id": alert_id,
        "incident_id": incident_id,
        "fingerprint": fingerprint,
        "route_mode": decision.route_mode,
        "logical_destination": decision.logical_destination,
        "digest_bucket": decision.digest_bucket,
        "send_immediate": decision.route_mode == ROUTE_IMMEDIATE and inserted,
        "suppression_reason": None if inserted else "duplicate_within_fingerprint",
        "policy_version": decision.policy_version,
        "volatile_fallback": True,
    }


def _record_delivery(cur, alert_id, route_mode, logical_destination, status, reason, rendered_message):
    """Record one delivery attempt against the occurrence it belongs to.

    Rewritten 2026-07-29. The previous version wrote the attempt row without an
    occurrence_id and then ran:

        UPDATE alert_notification_events SET last_delivery_status=..., delivery_count=delivery_count+1
        UPDATE alert_notification_events SET suppression_reason=..., last_suppression_at=now()

    Three defects, all from the module being written against the FIRST draft schema
    where alert_notification_events was a TABLE:

      1. It is now a derived VIEW joining occurrences to incidents. A join view is
         not auto-updatable in PostgreSQL, so both statements raise. Nothing caught
         it because the migration was unapplied and this path never ran.
      2. last_suppression_at does not exist on any table in the model.
      3. occurrence_id was left NULL on the attempt row, so the delivery could not
         be tied back to its occurrence — which is what BOTH unique indexes key on
         (occurrence_id, attempt_seq) and the partial one-sent-per-occurrence guard.

    The occurrence model already holds every fact those UPDATEs were reaching for:
    delivery state lives on alert_notification_deliveries (surfaced as
    last_delivery_status / last_delivery_at by the view), and the counters live on
    alert_incidents. Suppression reason is derived by the view from the
    occurrence's own notify/decision_reason and needs no retro-write.

    Counters are incremented ONLY when the insert actually took a row, so a retry
    that hits ON CONFLICT DO NOTHING cannot double-count.
    """
    msg_fp = _delivery_fingerprint(rendered_message or f"{alert_id}:{status}:{reason}")

    # The occurrence this delivery belongs to — latest for the alert_id.
    cur.execute(
        """SELECT occurrence_id, incident_id FROM alert_occurrences
            WHERE alert_id = %s ORDER BY occurrence_seq DESC LIMIT 1""",
        (alert_id,),
    )
    row = cur.fetchone()
    if not row:
        # No occurrence: the caller is delivering something that was never
        # published through the outbox. Record nothing rather than orphan a row.
        return
    occurrence_id, incident_id = row

    cur.execute(
        """
        INSERT INTO alert_notification_deliveries
            (occurrence_id, alert_id, incident_id, attempt_seq, logical_destination,
             route_mode, delivery_status, delivery_reason, message_fingerprint,
             rendered_message, completed_at)
        VALUES (
            %s, %s, %s,
            COALESCE((SELECT max(attempt_seq) + 1 FROM alert_notification_deliveries
                       WHERE occurrence_id = %s), 1),
            %s, %s, %s, %s, %s, %s,
            CASE WHEN %s IN ('sent', 'suppressed') THEN now() ELSE NULL END
        )
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (occurrence_id, alert_id, incident_id, occurrence_id,
         logical_destination, route_mode, status, reason, msg_fp,
         rendered_message, status),
    )
    inserted = cur.fetchone()
    if not inserted:
        # Conflict — one_sent_per_occurrence or (occurrence_id, attempt_seq).
        # The attempt is already recorded; do not move the counters again.
        return

    # LQ-20261107-1607: the work item this attempt answers is closed. Without this the occurrence's 'queued' row
    # stayed 'queued' forever beside a 'sent' attempt, so the queue age contract (queued <= 10 min) could never
    # tell a drained queue from a dead one.
    cur.execute(
        """UPDATE alert_notification_deliveries
              SET delivery_status = 'abandoned', delivery_reason = 'superseded_by_attempt', completed_at = now()
            WHERE occurrence_id = %s AND delivery_status = 'queued' AND id <> %s""",
        (occurrence_id, inserted[0]),
    )

    if status == "sent":
        cur.execute(
            """UPDATE alert_incidents
                  SET notified_count = notified_count + 1, last_notified_at = now()
                WHERE incident_id = %s""",
            (incident_id,),
        )
    elif status == "suppressed":
        cur.execute(
            "UPDATE alert_incidents SET suppressed_count = suppressed_count + 1 WHERE incident_id = %s",
            (incident_id,),
        )


def pending_immediate(limit: int = 50) -> list[dict[str, Any]]:
    conn = _db()
    if conn is None:
        rows = []
        for item in _MEM_EVENTS.values():
            if item["decision"].route_mode == ROUTE_IMMEDIATE:
                rows.append({
                    "alert_id": item["alert_id"],
                    "event": item["event"],
                    "logical_destination": item["decision"].logical_destination,
                })
        return rows[:limit]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.alert_id, e.logical_destination, e.payload
            FROM alert_notification_events e
            WHERE e.route_mode='IMMEDIATE'
              -- LQ-20261107-1607: claim only real work. "<> 'sent'" also claimed 'suppressed' (every SHADOW decision,
              -- whose message the legacy sender already delivered) and 'abandoned' (expired) rows, so flipping to
              -- ACTIVE would have re-sent the whole shadow history.
              AND e.last_delivery_status IN ('queued', 'failed')
              AND (e.expires_at IS NULL OR e.expires_at > now())
            ORDER BY e.created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [{"alert_id": r[0], "logical_destination": r[1], "payload": r[2]} for r in rows]


def resolve_channel_secret(logical_destination: str | None) -> tuple[str, str | None]:
    if logical_destination == APPROVALS_ONLY:
        return os.getenv("TRADEAI_PROPOSAL_ALERT_CHAT_ID", ""), os.getenv("TRADEAI_PROPOSAL_ALERT_THREAD_ID")
    if logical_destination == CRITICAL_OPERATIONS:
        return os.getenv("TRADEAI_GENERAL_ALERT_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID", ""), os.getenv("TRADEAI_GENERAL_ALERT_THREAD_ID")
    return os.getenv("TELEGRAM_CHAT_ID", ""), None


def deliver_immediate(send_func=None, limit: int = 50, *, mode: str | None = None) -> dict[str, Any]:
    """Send pending immediate alerts. Tests should pass send_func; production uses telegram_transport.

    LQ-20261107-1607: refuses unless the runtime mode is ACTIVE. In SHADOW/OFF the legacy sender owns delivery; a
    consumer that sends here duplicates every alert the operator already received.
    """
    effective = (mode or get_mode()).upper()
    if effective != "ACTIVE":
        return {"ok": False, "sent": 0, "suppressed": 0, "refused": f"runtime_mode_{effective.lower()}_legacy_owns_delivery"}
    if send_func is None:
        from telegram_transport import send_message
        send_func = send_message
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    sent = suppressed = 0
    conn = _db()
    for row in pending_immediate(limit):
        alert_id = row["alert_id"]
        event_payload = row.get("payload", {})
        ev_dict = (event_payload or {}).copy()
        event = ev_dict.get("payload")
        if isinstance(event_payload, dict) and "alert_type" in event_payload:
            event = event_payload
        if isinstance(event, dict):
            alert_event = AlertEvent(**{k: event.get(k) for k in AlertEvent.__dataclass_fields__.keys() if k in event})
        else:
            alert_event = AlertEvent(alert_type="operator_alert", source_system="unknown", source_producer="unknown")
        message = render_operator_message(alert_event, alert_id)
        chat_id, thread_id = resolve_channel_secret(row.get("logical_destination"))
        status = "suppressed"
        reason = "telegram_channel_not_configured"
        if token and chat_id:
            result = send_func(token=token, chat_id=chat_id, text=message, thread_id=thread_id)
            status = "sent" if result.get("ok") else "failed"
            reason = str(result.get("status_code") or result.get("error") or status)[:120]
        if conn is not None:
            with conn.cursor() as cur:
                _record_delivery(cur, alert_id, ROUTE_IMMEDIATE, row.get("logical_destination"), status, reason, message)
            conn.commit()
        sent += 1 if status == "sent" else 0
        suppressed += 1 if status == "suppressed" else 0
    return {"ok": True, "sent": sent, "suppressed": suppressed}


# ── the missing consumer (LQ-20261107-1815) ──────────────────────────────────────────────────────────────────────
#
# The migration designed this queue with claim semantics (claimed_by / claimed_at / retry_count, and the partial index
# alert_deliveries_claimable_idx over status IN ('queued','failed')), but no code ever claimed a row: deliver_immediate()
# above has no production caller and refuses outside ACTIVE, the occurrence store wrote terminal rows, and the hygiene
# lane closed the rest. Measured 2026-11-10 (audit-revalidation-20261110 §C1): 676 rows, 0 with a telegram_message_id,
# 0 with a claimant, 0 ever 'sent'. These functions are the consumer: claim, send through the Telegram chokepoint,
# record what the transport actually returned.

#: claimed_by for a row this process takes. Rule 11's shape: who, on which host, in which process.
CRITICAL_CLAIM_OWNER_PREFIX = "alert_outbox.critical"
#: Attempts after which a critical row is given up and left 'failed' for the hygiene lane and a human, never retried
#: forever. 3 = the transport gets two more chances after the first.
CRITICAL_MAX_ATTEMPTS = 3
#: A claim older than this belongs to a worker that died mid-send. Re-claimable, so a crash cannot orphan an alert.
CRITICAL_CLAIM_TTL_MIN = 15
#: Rows older than this are history, not an interruption: the same bound the hygiene lane uses for its stale class.
CRITICAL_MAX_AGE_H = 6

#: First line of a handover message. It tells the operator this alert was suppressed upstream, and it changes the
#: text so the Communications Editor's duplicate hash cannot HOLD the re-delivery as a repeat of a message it saw.
HANDOVER_MARK = "[critical alert re-delivered — the legacy sender suppressed the original]"

_CRITICAL_DUE_WHERE = """
       d.route_mode = 'IMMEDIATE'
   AND o.severity = 'critical'
   AND o.notify
   AND d.retry_count < %(max_attempts)s
   AND d.created_at >= now() - make_interval(hours => %(max_age_h)s)
   AND d.created_at <= now() - make_interval(secs => %(min_age_s)s)
   AND (
         d.delivery_status IN ('queued', 'failed')
      OR (d.delivery_status = 'claimed'
          AND (d.claimed_at IS NULL OR d.claimed_at < now() - make_interval(mins => %(ttl_min)s)))
       )
   -- One SENT row per occurrence is the table's own invariant; a second delivery would duplicate it.
   AND NOT EXISTS (SELECT 1 FROM alert_notification_deliveries s
                    WHERE s.occurrence_id = d.occurrence_id AND s.delivery_status = 'sent')
   AND (%(occurrence_id)s::bigint IS NULL OR d.occurrence_id = %(occurrence_id)s::bigint)
"""

_CRITICAL_SELECT_SQL = f"""
SELECT d.id, d.occurrence_id, d.alert_id, d.logical_destination, d.attempt_seq, d.retry_count,
       d.delivery_status, d.delivery_reason, o.alert_type, o.source_producer, o.symbol, o.severity,
       o.payload, o.observed_at
  FROM alert_notification_deliveries d
  JOIN alert_occurrences o ON o.occurrence_id = d.occurrence_id
 WHERE {_CRITICAL_DUE_WHERE}
 ORDER BY d.created_at ASC
 LIMIT %(limit)s
"""

_CRITICAL_CLAIM_SQL = f"""
WITH due AS (
    SELECT d.id
      FROM alert_notification_deliveries d
      JOIN alert_occurrences o ON o.occurrence_id = d.occurrence_id
     WHERE {_CRITICAL_DUE_WHERE}
     ORDER BY d.created_at ASC
     LIMIT %(limit)s
     FOR UPDATE OF d SKIP LOCKED
)
UPDATE alert_notification_deliveries d
   SET delivery_status = 'claimed', claimed_by = %(owner)s, claimed_at = now()
  FROM due
 WHERE d.id = due.id
RETURNING d.id
"""

_CRITICAL_DETAIL_SQL = """
SELECT d.id, d.occurrence_id, d.alert_id, d.logical_destination, d.attempt_seq, d.retry_count,
       d.delivery_status, d.delivery_reason, o.alert_type, o.source_producer, o.symbol, o.severity,
       o.payload, o.observed_at
  FROM alert_notification_deliveries d
  JOIN alert_occurrences o ON o.occurrence_id = d.occurrence_id
 WHERE d.id = ANY(%s)
 ORDER BY d.created_at ASC
"""


def claim_owner() -> str:
    """Who claims: module@host:pid. Never a secret, always enough to find the process that took the row."""
    import socket
    return f"{CRITICAL_CLAIM_OWNER_PREFIX}@{socket.gethostname()[:40]}:{os.getpid()}"


def _critical_params(*, occurrence_id: int | None, limit: int, min_age_s: int) -> dict[str, Any]:
    return {"occurrence_id": occurrence_id, "limit": int(limit), "min_age_s": int(min_age_s),
            "max_age_h": CRITICAL_MAX_AGE_H, "max_attempts": CRITICAL_MAX_ATTEMPTS,
            "ttl_min": CRITICAL_CLAIM_TTL_MIN, "owner": claim_owner()}


def critical_due(*, conn=None, occurrence_id: int | None = None, limit: int = 5, min_age_s: int = 0) -> list[dict[str, Any]]:
    """The CRITICAL rows a worker would claim right now. Read-only; the dry run and the apply share this shape."""
    own = conn is None
    conn = conn or _db()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(_CRITICAL_SELECT_SQL, _critical_params(occurrence_id=occurrence_id, limit=limit, min_age_s=min_age_s))
            cols = [c.name if hasattr(c, "name") else c[0] for c in (cur.description or [])]
            rows = [dict(zip(cols, r)) for r in (cur.fetchall() or [])]
    finally:
        if own:
            try:
                conn.rollback()  # a read holds no lock worth keeping
            except Exception:
                pass
    return rows


def _handover_message(row: dict[str, Any]) -> str:
    """The message for one claimed row: the operator rendering, marked when the legacy path suppressed the original."""
    payload = row.get("payload") or {}
    event = payload.get("payload") if isinstance(payload, dict) else None
    if isinstance(payload, dict) and "alert_type" in payload:
        event = payload
    if isinstance(event, dict):
        alert_event = AlertEvent(**{k: event.get(k) for k in AlertEvent.__dataclass_fields__.keys() if k in event})
    else:
        alert_event = AlertEvent(alert_type=row.get("alert_type") or "operator_alert", source_system="unknown",
                                 source_producer=row.get("source_producer") or "unknown",
                                 severity=row.get("severity") or "critical")
    message = render_operator_message(alert_event, row.get("alert_id"))
    if str(row.get("delivery_reason") or "").startswith("shadow_legacy_undelivered:"):
        return f"{HANDOVER_MARK}\n{message}"
    return message


def _send_critical_default(message: str, logical_destination: str | None) -> dict[str, Any]:
    """The Telegram chokepoint for one handover, addressed to an explicit chat id.

    Not ``telegram_transport`` directly: ``telegram_alert.send_telegram_with_id`` is the approved chokepoint (it
    normalizes links, writes the communications ledger row and returns the provider message id), and it is what
    ``check_telegram_chokepoint.py`` allows. The Communications Editor still applies inside it, so an editor hold is
    reported as such rather than as a delivery.

    It is a declared P1 intent (AGENTS.md §24.1) with ``dedupe_minutes=0``: a critical handover is never quiet-held,
    never digested, and never deduped -- the original reached nobody, and this process already bounds its own retries
    (``CRITICAL_MAX_ATTEMPTS``). The handover marker also changes the body, so the intent dedupe key cannot collide
    with the suppressed original in any case.
    """
    chat_id, thread_id = resolve_channel_secret(logical_destination)
    if not chat_id:
        return {"status": "failed", "reason": "telegram_channel_not_configured", "message_id": None}
    from telegram_alert import delivery_outcome, send_telegram_with_id
    out = send_telegram_with_id(message, False, chat_ids=[chat_id], thread_id=thread_id or None,
                                message_class="operator_alert", priority="P1", dedupe_minutes=0,
                                producer=CRITICAL_CLAIM_OWNER_PREFIX)
    ids = [str(x) for x in (out.get("message_ids") or []) if str(x).strip()]
    if ids:
        return {"status": "sent", "reason": None, "message_id": ids[0]}
    # Nothing came back. ``delivery_outcome`` is this CALL's typed result (``send_telegram`` resets the attempt
    # bucket on entry), so it distinguishes an editor hold from a failed or unconfigured transport. ``last_held_chunks``
    # would not: that bucket is process-wide and not cleared per send, so it can report an EARLIER message's hold.
    outcome = delivery_outcome(bool(out.get("accepted")))
    if outcome["status"] == "HELD":
        return {"status": "suppressed", "reason": "editor_held", "message_id": None}
    return {"status": "failed", "reason": f"telegram_{str(outcome['status']).lower()}", "message_id": None}


def deliver_critical(*, occurrence_id: int | None = None, limit: int = 5, min_age_s: int = 0,
                     send_func=None, conn=None, dry_run: bool = False) -> dict[str, Any]:
    """Claim CRITICAL IMMEDIATE rows and send them. The consumer this queue never had.

    ``dry_run`` claims nothing and sends nothing; it returns exactly the rows an apply would take. Production callers
    pass no ``send_func`` (the Telegram chokepoint); tests inject one.

    Every state change is recorded on the row itself, so a reader can answer "who sent it, when, with what receipt"
    without a log file: claimed_by/claimed_at at claim time, telegram_message_id + completed_at on success, a retry
    count and a reason on failure. A row is never sent twice: the claim excludes any occurrence that already has a
    'sent' row.
    """
    params = _critical_params(occurrence_id=occurrence_id, limit=limit, min_age_s=min_age_s)
    own = conn is None
    conn = conn or _db()
    if conn is None:
        return {"ok": False, "outcome": "durable_store_unavailable", "claimed": 0, "sent": 0, "failed": 0,
                "rows": []}
    if dry_run:
        rows = critical_due(conn=conn, occurrence_id=occurrence_id, limit=limit, min_age_s=min_age_s)
        if own:
            conn.close()
        return {"ok": True, "outcome": "dry_run", "would_claim": len(rows), "claimed": 0, "sent": 0, "failed": 0,
                "rows": [{k: r.get(k) for k in ("id", "occurrence_id", "alert_id", "logical_destination",
                                                "delivery_status", "delivery_reason", "alert_type", "severity",
                                                "retry_count", "observed_at")} for r in rows]}

    owner = params["owner"]
    try:
        with conn.cursor() as cur:
            cur.execute(_CRITICAL_CLAIM_SQL, params)
            claimed_ids = [r[0] for r in (cur.fetchall() or [])]
            rows = []
            if claimed_ids:
                cur.execute(_CRITICAL_DETAIL_SQL, (claimed_ids,))
                cols = [c.name if hasattr(c, "name") else c[0] for c in (cur.description or [])]
                rows = [dict(zip(cols, r)) for r in (cur.fetchall() or [])]
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        # Nothing below needs the claim transaction; the claim is durable on its own so a crash mid-send leaves a
        # 'claimed' row with claimed_by set, which the TTL makes re-claimable instead of lost.
        pass

    send_func = send_func or _send_critical_default
    sent = failed = suppressed = 0
    results = []
    for row in rows:
        message = _handover_message(row)
        try:
            outcome = send_func(message, row.get("logical_destination"))
        except Exception as exc:  # noqa: BLE001 — a sender failure is a failed ATTEMPT, never a lost claim
            outcome = {"status": "failed", "reason": type(exc).__name__[:60], "message_id": None}
        status = str(outcome.get("status") or "failed")
        reason = outcome.get("reason")
        message_id = outcome.get("message_id")
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE alert_notification_deliveries
                   SET delivery_status = %s,
                       delivery_reason = %s,
                       telegram_message_id = %s,
                       rendered_message = COALESCE(rendered_message, %s),
                       retry_count = retry_count + CASE WHEN %s = 'failed' THEN 1 ELSE 0 END,
                       completed_at = CASE WHEN %s IN ('sent','suppressed') THEN now() ELSE completed_at END
                 WHERE id = %s
                """,
                (status, reason, message_id, message, status, status, row.get("id")),
            )
        conn.commit()
        sent += 1 if status == "sent" else 0
        failed += 1 if status == "failed" else 0
        suppressed += 1 if status == "suppressed" else 0
        results.append({"id": row.get("id"), "occurrence_id": row.get("occurrence_id"), "alert_id": row.get("alert_id"),
                        "status": status, "reason": reason, "telegram_message_id": message_id})
    if own:
        conn.close()
    return {"ok": failed == 0, "outcome": "applied", "claimed": len(rows), "sent": sent, "failed": failed,
            "suppressed": suppressed, "claimed_by": owner, "rows": results}


def build_digest(bucket: str, *, now: datetime | None = None) -> dict[str, Any]:
    bucket = bucket.upper()
    now = now or datetime.now(timezone.utc)
    conn = _db()
    if conn is None:
        items = [x for x in _MEM_DIGEST if x["bucket"] == bucket]
        return _digest_from_events(bucket, [x["event"] for x in items], now=now)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.alert_type, e.source_producer, e.symbol, e.severity, e.operator_action_required, e.created_at, e.payload
            FROM alert_digest_queue q
            JOIN alert_notification_events e ON e.alert_id=q.alert_id
            WHERE q.digest_bucket=%s AND q.included_at IS NULL AND q.expires_at > now()
            ORDER BY e.created_at ASC
            """,
            (bucket,),
        )
        rows = cur.fetchall()
    events = []
    for r in rows:
        events.append(AlertEvent(
            alert_type=r[0], source_system="digest", source_producer=r[1], symbol=r[2],
            severity=r[3], operator_action_required=r[4], payload=r[6] or {},
        ))
    return _digest_from_events(bucket, events, now=now)


def _digest_from_events(bucket: str, events: list[AlertEvent], *, now: datetime) -> dict[str, Any]:
    from notification_url_builder import build_dashboard_url, sanitize_operator_message

    if not events:
        return {"ok": True, "bucket": bucket, "nonempty": False, "message": ""}
    counts: dict[str, int] = {}
    producers: dict[str, int] = {}
    critical = 0
    for ev in events:
        counts[ev.alert_type] = counts.get(ev.alert_type, 0) + 1
        producers[ev.source_producer] = producers.get(ev.source_producer, 0) + 1
        critical += 1 if ev.severity.lower() in {"critical", "urgent"} else 0
    top_types = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:5]
    top_producers = sorted(producers.items(), key=lambda x: (-x[1], x[0]))[:5]
    lines = [
        f"{bucket.title()} Digest - {now.astimezone().strftime('%Y-%m-%d %H:%M')}",
        f"{len(events)} queued item(s) · unresolved critical incidents: {critical}",
        "Top changes: " + " · ".join(f"{k} {v}" for k, v in top_types),
        "Repeated failures: " + (" · ".join(f"{k} {v}" for k, v in top_producers) if top_producers else "none"),
        "What changed: new digest queue items since the prior scheduled digest.",
        build_dashboard_url("/v3/reports"),
    ]
    message, violations = sanitize_operator_message("\n".join(lines))
    return {"ok": True, "bucket": bucket, "nonempty": True, "message": message, "violations": violations, "counts": counts}


def active_alerts(days: int = 7, limit: int = 200) -> list[dict[str, Any]]:
    conn = _db()
    if conn is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT alert_id, alert_type, source_system, source_producer, symbol, severity,
                   operator_action_required, operator_action_type, logical_destination, route_mode,
                   digest_bucket, incident_id, created_at, expires_at, acknowledged_at,
                   suppression_reason, last_delivery_status, last_delivery_at, duplicate_count
            FROM alert_notification_events
            WHERE resolved_at IS NULL
              AND created_at >= now() - (%s || ' days')::interval
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (int(days), int(limit)),
        )
        rows = cur.fetchall()
    cols = [
        "alert_id", "alert_type", "source_system", "source_producer", "symbol", "severity",
        "operator_action_required", "operator_action_type", "logical_destination", "route_mode",
        "digest_bucket", "incident_id", "created_at", "expires_at", "acknowledged_at",
        "suppression_reason", "last_delivery_status", "last_delivery_at", "duplicate_count",
    ]
    return [dict(zip(cols, r)) for r in rows]


def list_alert_settings(days: int = 7) -> dict[str, Any]:
    ensure_default_preferences()
    conn = _db()
    rows: list[dict[str, Any]] = []
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.alert_type, p.general_telegram, p.approval_telegram, p.command_center,
                       p.digest_bucket, p.ttl_seconds, p.dedupe_window_seconds, p.escalate_after_seconds,
                       p.sound_enabled, p.policy_version, p.row_version, p.updated_at,
                       p.last_delivery_at, p.last_suppression_reason,
                       COALESCE(v.volume,0) AS trailing_volume
                FROM operator_alert_preferences p
                LEFT JOIN (
                    SELECT alert_type, count(*) AS volume
                    FROM alert_notification_events
                    WHERE created_at >= now() - (%s || ' days')::interval
                    GROUP BY alert_type
                ) v ON v.alert_type=p.alert_type
                ORDER BY p.alert_type
                """,
                (int(days),),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    else:
        for alert_type, vals in sorted(DEFAULT_PREFERENCES.items()):
            rows.append({
                "alert_type": alert_type,
                "general_telegram": vals[0],
                "approval_telegram": vals[1],
                "command_center": vals[2],
                "digest_bucket": vals[3],
                "ttl_seconds": vals[4],
                "dedupe_window_seconds": vals[5],
                "escalate_after_seconds": vals[6],
                "sound_enabled": vals[7],
                "policy_version": POLICY_VERSION,
                "row_version": 1,
                "trailing_volume": 0,
                "last_delivery_at": None,
                "last_suppression_reason": None,
            })
    return {"ok": True, "policy_version": POLICY_VERSION, "days": days, "settings": rows}


def validate_preference_change(alert_type: str, proposed: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    approval = proposed.get("approval_telegram", "OFF")
    general = proposed.get("general_telegram", "OFF")
    command_center = bool(proposed.get("command_center", True))
    if approval != "OFF" and alert_type not in APPROVAL_ALLOWLIST:
        errors.append("approval_telegram_is_allowlist_only")
    if alert_type in PAPER_OR_CANDIDATE_TYPES and approval != "OFF":
        errors.append("paper_candidate_types_cannot_route_to_approvals")
    if alert_type in CRITICAL_IMMEDIATE_TYPES and general == "OFF" and approval == "OFF" and not command_center:
        errors.append("live_protection_failures_cannot_be_disabled_from_every_surface")
    if proposed.get("digest_bucket") not in {"RISK", "TRADING", "OPS"}:
        errors.append("invalid_digest_bucket")
    if proposed.get("ttl_seconds") is not None and int(proposed["ttl_seconds"]) > 7 * 86400 and alert_type not in CRITICAL_IMMEDIATE_TYPES:
        errors.append("active_alert_ttl_must_not_exceed_seven_days")
    return errors


def update_alert_setting(alert_type: str, body: dict[str, Any], *, actor: str = "operator") -> dict[str, Any]:
    ensure_default_preferences()
    conn = _db()
    if conn is None:
        errors = validate_preference_change(alert_type, body)
        return {"ok": not errors, "errors": errors, "volatile_fallback": True}
    with conn.cursor() as cur:
        cur.execute("SELECT row_to_json(p), row_version FROM operator_alert_preferences p WHERE alert_type=%s", (alert_type,))
        current = cur.fetchone()
        if not current:
            return {"ok": False, "errors": ["unknown_alert_type"]}
        old_value, row_version = current
        expected = int(body.get("row_version") or 0)
        if expected != int(row_version):
            return {"ok": False, "errors": ["row_version_conflict"], "current_row_version": row_version}
        proposed = dict(old_value)
        for key in ("general_telegram", "approval_telegram", "command_center", "digest_bucket",
                    "ttl_seconds", "dedupe_window_seconds", "escalate_after_seconds", "sound_enabled"):
            if key in body:
                proposed[key] = body[key]
        errors = validate_preference_change(alert_type, proposed)
        if errors:
            return {"ok": False, "errors": errors}
        cur.execute(
            """
            UPDATE operator_alert_preferences
            SET general_telegram=%s, approval_telegram=%s, command_center=%s, digest_bucket=%s,
                ttl_seconds=%s, dedupe_window_seconds=%s, escalate_after_seconds=%s, sound_enabled=%s,
                row_version=row_version+1, updated_at=now(), updated_by=%s
            WHERE alert_type=%s AND row_version=%s
            RETURNING row_version
            """,
            (
                proposed["general_telegram"], proposed["approval_telegram"], proposed["command_center"],
                proposed["digest_bucket"], proposed["ttl_seconds"], proposed["dedupe_window_seconds"],
                proposed.get("escalate_after_seconds"), proposed["sound_enabled"], actor, alert_type, row_version,
            ),
        )
        new_version = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO operator_alert_preference_audit(alert_type, old_value, new_value, changed_by, change_reason)
            VALUES (%s,%s::jsonb,%s::jsonb,%s,%s)
            """,
            (alert_type, _json(old_value), _json(proposed), actor, str(body.get("change_reason") or "settings_update")[:240]),
        )
    conn.commit()
    return {"ok": True, "alert_type": alert_type, "row_version": new_version}


def settings_projection(days: int = 7) -> dict[str, Any]:
    conn = _db()
    if conn is None:
        return {"ok": True, "days": days, "before": {}, "after": {}, "note": "database unavailable"}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT route_mode, COALESCE(logical_destination,'NONE'), count(*)
            FROM alert_notification_events
            WHERE created_at >= now() - (%s || ' days')::interval
            GROUP BY route_mode, COALESCE(logical_destination,'NONE')
            """,
            (int(days),),
        )
        rows = cur.fetchall()
    current = {f"{r[0]}:{r[1]}": int(r[2]) for r in rows}
    return {"ok": True, "days": days, "before": current, "after": current}


def synthetic_test_send(alert_type: str) -> dict[str, Any]:
    if alert_type not in DEFAULT_PREFERENCES:
        return {"ok": False, "errors": ["unknown_alert_type"]}
    event = AlertEvent(
        alert_type=alert_type,
        source_system="synthetic_test",
        source_producer="command_center_alert_settings",
        entity_id=f"synthetic-{alert_type}",
        severity="info",
        operator_action_required=alert_type in APPROVAL_ALLOWLIST or alert_type in CRITICAL_IMMEDIATE_TYPES,
        authorization_or_order_id=f"synthetic-{alert_type}" if alert_type in APPROVAL_ALLOWLIST else None,
        payload={"message": f"[SYNTHETIC TEST] {alert_type} settings test. No production channel or broker action."},
    )
    decision = publish_event(event)
    return {"ok": True, "synthetic": True, "decision": decision}
