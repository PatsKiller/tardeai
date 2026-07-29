#!/usr/bin/env python3
"""Occurrence-based persistence — makes should_notify() authoritative.

Every observation records an occurrence against an incident, and the notify decision
is computed from PERSISTED prior state rather than assumed. The decision and the
inputs it was computed from are stored together, so a later reader can answer "why
was this suppressed?" without re-deriving it.

Concurrency: the incident row is claimed with SELECT ... FOR UPDATE inside the same
transaction that appends the occurrence, so two publishers observing the same
condition simultaneously serialise — one sees the other's occurrence as prior state
and correctly suppresses. The partial unique index on open incidents is the backstop.

Nothing here sends. Delivery rows are written in 'queued' state for the worker.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from alert_dedupe import PriorState, should_notify

MATERIAL_REASONS = {
    "severity_increased", "operator_action_now_required", "state_version_changed",
    "recurred_after_resolution", "condition_resolved",
}


def _json(v: Any) -> str:
    return json.dumps(v or {}, separators=(",", ":"), default=str)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_prior_state(cur, dedupe_key: str, *, correlation_key: str | None = None) -> tuple[dict | None, PriorState | None]:
    """Claim the OPEN incident for this condition and return (row, PriorState).

    FOR UPDATE serialises concurrent publishers of the same condition.
    """
    cur.execute(
        """
        SELECT incident_id, dedupe_key, status, severity, operator_action_required,
               state_version, last_notified_at, last_seen_at, resolved_at,
               acknowledged_at, occurrence_count, notified_count, suppressed_count,
               route_mode, logical_destination, digest_bucket, correlation_key
          FROM alert_incidents
         WHERE status = 'open'
           AND (dedupe_key = %s OR (%s IS NOT NULL AND correlation_key = %s))
         ORDER BY (dedupe_key = %s) DESC, last_seen_at DESC
         LIMIT 1
         FOR UPDATE
        """,
        (dedupe_key, correlation_key, correlation_key, dedupe_key),
    )
    row = cur.fetchone()
    if not row:
        return None, None
    cols = [d[0] for d in cur.description]
    rec = dict(zip(cols, row))
    prior = PriorState(
        last_notified_at=_aware(rec["last_notified_at"]),
        last_seen_at=_aware(rec["last_seen_at"]),
        severity=rec["severity"],
        operator_action_required=bool(rec["operator_action_required"]),
        state_version=rec["state_version"],
        resolved_at=_aware(rec["resolved_at"]),
        acknowledged_at=_aware(rec["acknowledged_at"]),
        occurrence_count=int(rec["occurrence_count"] or 0),
        notified_count=int(rec["notified_count"] or 0),
    )
    return rec, prior


def record_occurrence(
    conn,
    *,
    incident_id: str,
    alert_id: str,
    dedupe_key: str,
    event,                       # AlertEvent
    route,                       # ResolvedRoute
    observed_at: datetime,
    correlation_key: str | None = None,
    resolving: bool = False,
    runtime_mode: str = "OFF",
) -> dict[str, Any]:
    """Append one occurrence, applying should_notify() against persisted prior state.

    Returns the structured publish result. Single transaction: prior-state claim,
    decision, occurrence append, incident update, and delivery/digest enqueue either
    all land or none do.
    """
    observed_at = _aware(observed_at) or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        rec, prior = load_prior_state(cur, dedupe_key, correlation_key=correlation_key)

        decision = should_notify(
            prior,
            now=observed_at,
            severity=event.severity,
            operator_action_required=bool(event.operator_action_required),
            state_version=str(event.state_version or "1"),
            dedupe_window_seconds=int(route.dedupe_window_seconds or 0),
            escalate_after_seconds=route.escalate_after_seconds,
            resolving=resolving,
        )
        material = decision.reason in MATERIAL_REASONS

        if rec is None:
            # New incident. The partial unique index on open incidents is what makes a
            # post-resolution recurrence legal rather than a constraint violation.
            cur.execute(
                """
                INSERT INTO alert_incidents
                    (incident_id, dedupe_key, alert_type, source_system, source_producer,
                     account_id, symbol, correlation_key, status, severity,
                     operator_action_required, operator_action_type, state_version,
                     route_mode, logical_destination, digest_bucket, policy_version,
                     environment, synthetic, delivery_prohibited,
                     first_seen_at, last_seen_at, expires_at, occurrence_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
                RETURNING incident_id
                """,
                (incident_id, dedupe_key, event.alert_type, event.source_system,
                 event.source_producer, event.account_id, event.symbol, correlation_key,
                 event.severity, bool(event.operator_action_required),
                 event.operator_action_type, str(event.state_version or "1"),
                 route.route_mode, route.logical_destination, route.digest_bucket,
                 route.policy_version,
                 (event.payload or {}).get("environment", "production"),
                 bool((event.payload or {}).get("synthetic")),
                 bool((event.payload or {}).get("delivery_prohibited")),
                 observed_at, observed_at,
                 observed_at + __import__("datetime").timedelta(seconds=int(route.ttl_seconds or 86400))),
            )
            incident_id = cur.fetchone()[0]
            seq = 1
        else:
            incident_id = rec["incident_id"]
            seq = decision.occurrence_seq

        cur.execute(
            """
            INSERT INTO alert_occurrences
                (alert_id, incident_id, occurrence_seq, dedupe_key, observed_at,
                 alert_type, source_producer, symbol, severity, operator_action_required,
                 state_version, payload, notify, decision_reason, is_escalation,
                 is_resolution, is_material_transition, suppressed_until, decision_inputs,
                 route_mode, logical_destination, digest_bucket, runtime_mode)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
            RETURNING occurrence_id
            """,
            (alert_id, incident_id, seq, dedupe_key, observed_at,
             event.alert_type, event.source_producer, event.symbol, event.severity,
             bool(event.operator_action_required), str(event.state_version or "1"),
             _json(event.payload), decision.notify, decision.reason,
             decision.is_escalation, decision.is_resolution, material,
             decision.suppressed_until,
             _json({"prior": asdict(prior) if prior else None,
                    "dedupe_window_seconds": route.dedupe_window_seconds,
                    "escalate_after_seconds": route.escalate_after_seconds,
                    "observed_at": observed_at.isoformat(),
                    "resolving": resolving}),
             route.route_mode, route.logical_destination, route.digest_bucket, runtime_mode),
        )
        occurrence_id = cur.fetchone()[0]

        # Incident state advances from the decision, never from raw event data alone.
        cur.execute(
            """
            UPDATE alert_incidents
               SET last_seen_at = %s,
                   occurrence_count = occurrence_count + 1,
                   notified_count = notified_count + CASE WHEN %s THEN 1 ELSE 0 END,
                   suppressed_count = suppressed_count + CASE WHEN %s THEN 0 ELSE 1 END,
                   last_notified_at = CASE WHEN %s THEN %s ELSE last_notified_at END,
                   severity = CASE WHEN %s THEN %s ELSE severity END,
                   operator_action_required = operator_action_required OR %s,
                   state_version = %s,
                   symbol = COALESCE(symbol, %s),
                   resolved_at = CASE WHEN %s THEN %s ELSE NULL END,
                   status = CASE WHEN %s THEN 'resolved' ELSE 'open' END
             WHERE incident_id = %s
            """,
            (observed_at, decision.notify, decision.notify,
             decision.notify, observed_at,
             decision.reason == "severity_increased", event.severity,
             bool(event.operator_action_required), str(event.state_version or "1"),
             event.symbol,
             decision.is_resolution, observed_at,
             decision.is_resolution, incident_id),
        )

        queued = delivered = False
        delivery_id = None
        if decision.notify and route.route_mode == "IMMEDIATE" and not route.suppression_reason:
            cur.execute(
                """
                INSERT INTO alert_notification_deliveries
                    (occurrence_id, alert_id, incident_id, attempt_seq, logical_destination,
                     route_mode, delivery_status, delivery_reason)
                VALUES (%s,%s,%s,1,%s,'IMMEDIATE','queued',%s)
                RETURNING id
                """,
                (occurrence_id, alert_id, incident_id, route.logical_destination, decision.reason),
            )
            delivery_id = cur.fetchone()[0]
            queued = True
        elif decision.notify and route.route_mode == "DIGEST" and route.digest_bucket:
            cur.execute(
                """
                INSERT INTO alert_digest_queue
                    (occurrence_id, alert_id, incident_id, digest_bucket, summary_group, synthetic)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (occurrence_id, digest_bucket) DO NOTHING
                """,
                (occurrence_id, alert_id, incident_id, route.digest_bucket,
                 f"{event.source_producer}:{event.alert_type}",
                 bool((event.payload or {}).get("synthetic"))),
            )
            queued = True

    conn.commit()
    return {
        "accepted": True,
        "mode": runtime_mode,
        "route_mode": route.route_mode,
        "queued": queued,
        "delivered": delivered,
        "suppressed": not decision.notify,
        "suppression_reason": None if decision.notify else decision.reason,
        "alert_id": alert_id,
        "incident_id": incident_id,
        "occurrence_id": occurrence_id,
        "delivery_id": delivery_id,
        "decision": decision.as_dict(),
        "material_transition": material,
    }
