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

Nothing here sends. A delivery row is written as work for the worker ('queued') only when something will drain it:
under ACTIVE, and under SHADOW only for a CRITICAL immediate decision the legacy sender reports it did NOT deliver
(LQ-20261107-1815). Everything else stays a terminal row, so the queue never holds work nobody owns.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from alert_dedupe import PriorState, should_notify

#: delivery_reason prefix of the terminal row a non-ACTIVE (SHADOW/OFF) IMMEDIATE decision records: the legacy sender
#: owned delivery AND reports it delivered, so the row is evidence of the decision, never work for a consumer
#: (LQ-20261107-1607).
SHADOW_DELIVERY_REASON_PREFIX = "shadow_legacy_owns_delivery:"

#: delivery_reason prefix of the WORK row a non-ACTIVE IMMEDIATE decision records when the legacy sender reports it did
#: NOT deliver and the alert is critical: the operator has received nothing, so the normalized plane owns this one.
#: Measured 2026-11-10 (audit-revalidation-20261110 §C1): 55 % of critical immediate decisions since 11-07 were
#: suppressed by the legacy router and 0 % were delivered by the normalized outbox, because this row said "the legacy
#: sender owns it" whether or not it had actually sent (LQ-20261107-1815).
SHADOW_UNDELIVERED_REASON_PREFIX = "shadow_legacy_undelivered:"

#: delivery_reason prefix of the terminal row a non-ACTIVE IMMEDIATE decision records when the legacy sender OBSERVED
#: that it did NOT deliver, and the alert is not critical (a critical one is handed over as QUEUED work above).
#: Before LQ-20261107-1841 this row said "the legacy sender owns delivery" about a message that never left the process.
LEGACY_SEND_FAILED_REASON_PREFIX = "legacy_send_failed:"

#: Severity whose failure to reach the operator is itself an incident. Matched case-insensitively against the
#: occurrence's own severity; the routing decision has already decided this alert is worth interrupting for.
CRITICAL_SEVERITY = "critical"

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


def load_prior_state(cur, dedupe_key: str, *, correlation_key: str | None = None,
                     incident_id: str | None = None) -> tuple[dict | None, PriorState | None]:
    """Claim the incident for this condition and return (row, PriorState).

    FOR UPDATE serialises concurrent publishers of the same condition.

    An OPEN incident is preferred. When none matches and `incident_id` is supplied,
    fall back to the exact primary key across ANY status, because a resolved or
    expired incident keeps its row and `incident_id_for()` is deterministic: the next
    occurrence of that same condition computes the same id the primary key already
    holds. Without the fallback `record_occurrence` took its "new incident" branch and
    the INSERT died on alert_incidents_pkey. Measured 2026-09-21: 9,223 such
    occurrences across 64 log files were DELIVERED to the operator and never recorded
    (`telegram_alert.py` catches it as "shadow persist skipped" so bookkeeping can
    never break an alert -- which is correct, and is why this went unnoticed).

    The fallback keys on the primary key, never on dedupe_key-without-status: several
    CLOSED incidents may share a dedupe_key, so that lookup would return an arbitrary
    one. It cannot break the one-open-incident-per-condition invariant either, since
    it only runs when no open row matched.

    Loading the closed row is also what makes NOTIFY_RECURRED_AFTER_RESOLUTION
    reachable (`alert_dedupe.py`): that decision needs `prior.resolved_at`, and the
    UPDATE at the end of `record_occurrence` already flips status back to 'open' and
    clears resolved_at whenever the decision is not itself a resolution. Both halves
    of post-resolution recurrence were built and correct; only this lookup broke them.
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
    if not row and incident_id:
        # No OPEN incident for this condition. It may have been resolved or expired
        # earlier; that row still exists under this exact primary key.
        cur.execute(
            """
            SELECT incident_id, dedupe_key, status, severity, operator_action_required,
                   state_version, last_notified_at, last_seen_at, resolved_at,
                   acknowledged_at, occurrence_count, notified_count, suppressed_count,
                   route_mode, logical_destination, digest_bucket, correlation_key
              FROM alert_incidents
             WHERE incident_id = %s
             LIMIT 1
             FOR UPDATE
            """,
            (incident_id,),
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


def immediate_delivery_row(*, runtime_mode: str, notify: bool, route_mode: str | None,
                           suppression_reason: str | None, severity: str | None,
                           decision_reason: str, legacy_delivered: bool | None = None,
                           legacy_message_id: str | None = None) -> dict[str, Any] | None:
    """The delivery row one occurrence writes, or None when it writes no IMMEDIATE row at all.

    Pure, so the ownership rule is testable without a database. Four outcomes:

      ACTIVE                                   -> 'queued'      (the normalized outbox owns delivery)
      SHADOW/OFF, critical, NOT delivered      -> 'queued'      (handover: the legacy send reached nobody)
      SHADOW/OFF, anything else, NOT delivered -> 'suppressed'  (terminal: 'legacy_send_failed:<decision>')
      SHADOW/OFF, delivered                    -> 'suppressed'  (terminal: 'shadow_legacy_owns_delivery:<decision>')

    ``legacy_delivered`` is what the legacy sender OBSERVED (``telegram_alert._legacy_send`` returns it). ``None``
    means nobody asked it, and for a critical alert that is NOT a reason to call the alert delivered: the safe
    direction for a critical is one possible duplicate, never a silent loss. A non-critical row keeps the old
    behaviour exactly, so the shadow history is not re-sent.

    ``legacy_message_id`` (LQ-20261107-1841) is the provider id of the message the sender actually delivered — the
    receipt C1 needs. It rides the row the sender already wrote; nothing new is sent. A delivered send with no id
    (a held chunk, a caller that bypassed the transport) stores None, which stays NOT OBSERVABLE rather than
    inventing one.
    """
    if not (notify and route_mode == "IMMEDIATE" and not suppression_reason):
        return None
    if str(runtime_mode or "").upper() == "ACTIVE":
        return {"status": "queued", "reason": decision_reason, "queued": True, "handover": False,
                "telegram_message_id": None}
    if str(severity or "").strip().lower() == CRITICAL_SEVERITY and legacy_delivered is not True:
        return {"status": "queued", "reason": f"{SHADOW_UNDELIVERED_REASON_PREFIX}{decision_reason}",
                "queued": True, "handover": True, "telegram_message_id": None}
    if legacy_delivered is False:
        # The legacy sender observed a failed send. Saying "the legacy sender owns delivery" about a message that
        # never left is the same lie LQ-1815 fixed for criticals, one severity down: name the failure instead.
        return {"status": "suppressed", "reason": f"{LEGACY_SEND_FAILED_REASON_PREFIX}{decision_reason}",
                "queued": False, "handover": False, "telegram_message_id": None}
    return {"status": "suppressed", "reason": f"{SHADOW_DELIVERY_REASON_PREFIX}{decision_reason}",
            "queued": False, "handover": False,
            "telegram_message_id": (str(legacy_message_id) if legacy_message_id else None)}


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
    legacy_delivered: bool | None = None,
    legacy_message_id: str | None = None,
) -> dict[str, Any]:
    """Append one occurrence, applying should_notify() against persisted prior state.

    Returns the structured publish result. Single transaction: prior-state claim,
    decision, occurrence append, incident update, and delivery/digest enqueue either
    all land or none do. ``legacy_message_id`` is the provider id of the legacy send
    this observation is about, written onto the delivery row as the receipt
    (LQ-20261107-1841); it is None whenever no send was observed.
    """
    observed_at = _aware(observed_at) or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        # incident_id is passed so a resolved/expired incident can be reclaimed by its
        # primary key when no OPEN row matches; without it the INSERT below collides.
        rec, prior = load_prior_state(cur, dedupe_key, correlation_key=correlation_key,
                                      incident_id=incident_id)

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
            reopened = False
        else:
            incident_id = rec["incident_id"]
            seq = decision.occurrence_seq
            reopened = rec.get("status") not in (None, "open") and not decision.is_resolution

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

        # Incident state advances from the decision, never from raw event data alone. `material` (the module's own
        # MATERIAL_REASONS) is exactly the set of change signals that notify even when the condition was acknowledged:
        # those clear the acknowledgement, because it answered a condition the operator has now seen change. An
        # ordinary window-elapsed repeat is not material - it is the case the acknowledgement exists to silence.
        cur.execute(
            """
            UPDATE alert_incidents
               SET last_seen_at = %s,
                   -- LQ-20261107-2146: a REOPENED incident (resolved/expired row reclaimed by primary key) is a new
                   -- episode: first_seen_at restarts, so "first seen" never predates the gap it describes.
                   -- LQ-20261107-2667 (REVIEW-2653 B1): occurrence_count does NOT restart. It is the seq source
                   -- (alert_dedupe: seq = count + 1) and alert_occurrences is UNIQUE (incident_id, occurrence_seq).
                   first_seen_at = CASE WHEN %s THEN %s ELSE first_seen_at END,
                   occurrence_count = occurrence_count + 1,
                   notified_count = notified_count + CASE WHEN %s THEN 1 ELSE 0 END,
                   suppressed_count = suppressed_count + CASE WHEN %s THEN 0 ELSE 1 END,
                   last_notified_at = CASE WHEN %s THEN %s ELSE last_notified_at END,
                   severity = CASE WHEN %s THEN %s ELSE severity END,
                   operator_action_required = operator_action_required OR %s,
                   state_version = %s,
                   symbol = COALESCE(symbol, %s),
                   resolved_at = CASE WHEN %s THEN %s ELSE NULL END,
                   status = CASE WHEN %s THEN 'resolved' ELSE 'open' END,
                   -- cx-openai D52 triage on #2680: a MATERIAL change invalidates the acknowledgement. Without this the
                   -- first changed occurrence notified, and the NEXT one reloaded the old acknowledgement and was
                   -- suppressed as "acknowledged condition unchanged" - so an operator who acknowledged a warning once
                   -- stopped hearing about the incident as it got worse. An acknowledgement answers the condition the
                   -- operator saw; when severity, required action, state version or resolution change, they have not
                   -- seen this one.
                   acknowledged_at = CASE WHEN %s THEN NULL ELSE acknowledged_at END,
                   acknowledged_by = CASE WHEN %s THEN NULL ELSE acknowledged_by END
             WHERE incident_id = %s
            """,
            (observed_at, reopened, observed_at, decision.notify, decision.notify,
             decision.notify, observed_at,
             decision.reason == "severity_increased", event.severity,
             bool(event.operator_action_required), str(event.state_version or "1"),
             event.symbol,
             decision.is_resolution, observed_at,
             decision.is_resolution,
             material, material,
             incident_id),
        )

        queued = delivered = False
        delivery_id = None
        row = immediate_delivery_row(runtime_mode=runtime_mode, notify=decision.notify,
                                     route_mode=route.route_mode, suppression_reason=route.suppression_reason,
                                     severity=event.severity, decision_reason=decision.reason,
                                     legacy_delivered=legacy_delivered,
                                     legacy_message_id=legacy_message_id)
        if row is not None:
            # LQ-20261107-1607 measured the old rule's cost: every SHADOW row said "the legacy sender owns delivery"
            # whether or not it had sent, and one deliver_immediate() call would have re-sent the whole history.
            # LQ-20261107-1815 keeps that guard for what the legacy path delivered and adds the one case it got
            # wrong: a CRITICAL alert the legacy router suppressed reached nobody, so it is queued for the worker
            # that now exists (alert_outbox.deliver_critical) instead of being recorded as delivered.
            # LQ-20261107-1841: the receipt rides this row. A delivered legacy send stores the provider message id
            # here, so the occurrence's chain closes (generated -> queued -> delivered -> received) instead of
            # depending on a second table that only the gateway path writes. A queued row has no id yet: the consumer
            # that sends it writes one when it does.
            cur.execute(
                """
                INSERT INTO alert_notification_deliveries
                    (occurrence_id, alert_id, incident_id, attempt_seq, logical_destination,
                     route_mode, delivery_status, delivery_reason, telegram_message_id, completed_at)
                VALUES (%s,%s,%s,1,%s,'IMMEDIATE',%s,%s,%s, CASE WHEN %s THEN NULL ELSE now() END)
                RETURNING id
                """,
                (occurrence_id, alert_id, incident_id, route.logical_destination,
                 row["status"], row["reason"], row.get("telegram_message_id"), row["queued"]),
            )
            delivery_id = cur.fetchone()[0]
            queued = row["queued"]
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
