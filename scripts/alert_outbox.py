#!/usr/bin/env python3
"""Durable alert event/outbox pipeline for normalized operator notifications."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any

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


def publish_legacy_message(message: str, *, source_producer: str = "legacy_send_telegram", bypass_router: bool = False) -> dict[str, Any]:
    event = classify_legacy_message(message, source_producer=source_producer)
    payload = dict(event.payload)
    payload["bypass_router_requested"] = bool(bypass_router)
    event = AlertEvent(**{**event.__dict__, "payload": payload})
    return publish_event(event)


def publish_event(event: AlertEvent) -> dict[str, Any]:
    decision = route_event(event)
    fingerprint = alert_fingerprint(event)
    alert_id = alert_id_for(fingerprint)
    incident_id = incident_id_for(event)
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
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_notification_events
                (alert_id, alert_type, source_system, source_producer, entity_id, account_id, symbol,
                 severity, operator_action_required, operator_action_type, logical_destination, route_mode,
                 digest_bucket, incident_id, fingerprint, state_version, authorization_or_order_id,
                 session_ref, order_ref, payload, policy_version, expires_at, suppression_reason)
                VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                ON CONFLICT (fingerprint) DO UPDATE SET
                    updated_at = now(),
                    severity = EXCLUDED.severity,
                    operator_action_required = EXCLUDED.operator_action_required,
                    operator_action_type = EXCLUDED.operator_action_type,
                    logical_destination = EXCLUDED.logical_destination,
                    route_mode = EXCLUDED.route_mode,
                    digest_bucket = EXCLUDED.digest_bucket,
                    payload = EXCLUDED.payload,
                    expires_at = EXCLUDED.expires_at,
                    suppression_reason = EXCLUDED.suppression_reason,
                    duplicate_count = alert_notification_events.duplicate_count + 1
                RETURNING alert_id, (xmax = 0) AS inserted, duplicate_count
                """,
                (
                    alert_id, event.alert_type, event.source_system, event.source_producer, event.entity_id,
                    event.account_id, event.symbol, event.severity, event.operator_action_required,
                    event.operator_action_type, decision.logical_destination, decision.route_mode,
                    decision.digest_bucket, incident_id, fingerprint, event.state_version,
                    event.authorization_or_order_id, event.session_ref, event.order_ref, _json(payload),
                    decision.policy_version, expires_at, decision.suppression_reason,
                ),
            )
            row = cur.fetchone()
            inserted = bool(row[1]) if row else True
            if decision.route_mode == ROUTE_DIGEST and decision.digest_bucket:
                cur.execute(
                    """
                    INSERT INTO alert_digest_queue(alert_id, digest_bucket, summary_group)
                    VALUES (%s,%s,%s)
                    ON CONFLICT(alert_id, digest_bucket) DO NOTHING
                    """,
                    (alert_id, decision.digest_bucket, f"{event.source_producer}:{event.alert_type}"),
                )
            status = "queued" if decision.route_mode in (ROUTE_IMMEDIATE, ROUTE_DIGEST) else "suppressed"
            reason = "new_incident" if inserted else "dedupe_update"
            if not inserted and decision.route_mode == ROUTE_IMMEDIATE:
                status = "suppressed"
                reason = "duplicate_within_fingerprint"
            _record_delivery(cur, alert_id, decision.route_mode, decision.logical_destination, status, reason, None)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

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
        """,
        (occurrence_id, alert_id, incident_id, occurrence_id,
         logical_destination, route_mode, status, reason, msg_fp,
         rendered_message, status),
    )
    if cur.rowcount != 1:
        # Conflict — one_sent_per_occurrence or (occurrence_id, attempt_seq).
        # The attempt is already recorded; do not move the counters again.
        return

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
              AND COALESCE(e.last_delivery_status,'') <> 'sent'
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


def deliver_immediate(send_func=None, limit: int = 50) -> dict[str, Any]:
    """Send pending immediate alerts. Tests should pass send_func; production uses telegram_transport."""
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
