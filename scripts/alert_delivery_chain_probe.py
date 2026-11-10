#!/usr/bin/env python3
"""alert-delivery-chain-probe — the measured C1 chain, per alert, read-only (LQ-20261107-1839).

WHAT IT PROVES.  For every critical/urgent alert occurrence in the last N days (default 7), the four links an operator
acceptance test names — generated -> queued -> delivered -> received — are each a timestamp the runtime actually wrote,
or the probe says which link is missing and why.  It never infers a link.  A provider message id is a receipt; a sender
that returned True about itself is not, and the probe files it under ``receipt_unobservable``.

SPINE.  ``alert_occurrences`` is the router's own record of every alert it decided about (``notify``,
``decision_reason``, ``route_mode``), so it is the only table that can say "this alert existed and was or was not
meant to reach the operator".  ``alert_events`` is a separate legacy ledger; it is not joinable to an occurrence by
key and is deliberately not used as the spine.

LINKS.
  generated   ``alert_occurrences.recorded_at`` — always present.
  queued      IMMEDIATE: ``alert_notification_deliveries.created_at``.  DIGEST: ``alert_digest_queue.queued_at``.
  delivered   IMMEDIATE: the delivery row's ``completed_at`` with ``delivery_status='sent'``, or the nearest
              ``communication_events`` row the legacy sender wrote for the same message text (its
              ``provider_settled_at`` and ``provider_message_id``).  DIGEST: ``alert_digest_queue.included_at`` —
              the batch, so the per-alert provider receipt is NOT OBSERVABLE by construction.
  received    a Telegram/provider message id (+ settlement).  ``NOT OBSERVABLE`` when the only evidence is the legacy
              sender's own ``legacy_delivered`` flag.
  read/ack    ``communication_events.acknowledged_at`` — no reader telemetry exists today, so it is reported as NOT
              OBSERVABLE rather than assumed.

The occurrence -> communication_events match is the exact 48-character message prefix the legacy sender uses for its
subject key (``telegram_alert.py``: ``subject_key = f"telegram:{message_class}:{(message or '')[:48]}"``), restricted
to a -5 s..+90 s window around the occurrence so a repeating message cannot be credited with a neighbour's receipt.

READ-ONLY.  The connection is opened with ``default_transaction_read_only=on`` and ``conn.set_session(readonly=True)``.
Nothing here sends, writes, re-queues, acknowledges or touches a credential.  ``operator_contact.json`` is never read.
MBI_BEHAVIOR = 0: nothing here sizes, orders or touches a broker.

VERDICTS ARE COMPUTED FROM ROWS.  No DB is ``UNVERIFIABLE``, never OK and never zero.

Usage:
    python3 scripts/alert_delivery_chain_probe.py                 # JSON summary, 7 days
    python3 scripts/alert_delivery_chain_probe.py --days 7 --table
    python3 scripts/alert_delivery_chain_probe.py --json-out /tmp/chain.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "AlertDeliveryChainProbe@v1"

#: The scope the operator named as "P0/P1/critical". ``alert_occurrences.severity`` carries critical/urgent; P0/P1 in
#: ``payload.intent_priority`` is a router priority that also covers info telemetry (2,689 rows/7 d), so it is reported
#: as a column but is not the scope.  A future severity is a code change here, not a silent widening.
SEVERE_SEVERITIES = ("critical", "urgent")

#: The IMMEDIATE queue contract, mirrored from the hygiene lane (kept explicit so a probe never calls a row "stuck"
#: under a bound that lane does not enforce).  A test pins the two pairs equal.
QUEUE_MAX_AGE_MIN = 10
CONSUMER_CLAIM_TTL_MIN = 15

RECEIPT_NOT_OBSERVABLE = "NOT OBSERVABLE"

#: Break classes.  Every string this module emits as a defect is one of these prefixes, so a consumer can group.
BREAK_CLASSES = (
    "not_queued",
    "stuck_in_queue",
    "orphaned_claim",
    "send_failed",
    "legacy_undelivered_queued",
    "held_by_editor",
    "not_delivered",
    "delivered_without_receipt",
    "receipt_unobservable",
    "queue_stage_missing",
    "digest_never_claimed",
    "digest_claimed_never_included",
    "deduped_uncovered",
    "no_push_route",
    "router_declined",
    "router_declined_but_sent",
)

#: Defects that say "the chain cannot be closed from evidence" rather than "a link is known broken".  The operator's
#: rule is say NOT OBSERVABLE, never assume; so these are counted separately from a proven loss.
OBSERVABILITY_DEFECTS = ("receipt_unobservable", "delivered_without_receipt")

SHADOW_OWNS = "shadow_legacy_owns_delivery:"
SHADOW_UNDELIVERED = "shadow_legacy_undelivered:"
EXPIRED_SHADOW = "expired:shadow_legacy_owned_delivery"


# --------------------------------------------------------------------------------------------------------------- utils
def _iso(v: Any) -> Optional[str]:
    if isinstance(v, str):
        return v or None
    if not isinstance(v, datetime):
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).isoformat()


def _dt(v: Any) -> Optional[datetime]:
    """A datetime or an ISO-8601 string (the probe keeps timestamps as ISO strings in its own output)."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def _age_min(created: Any, now: datetime) -> Optional[float]:
    d = _dt(created)
    if d is None:
        return None
    return (now - d).total_seconds() / 60.0


def percentile(values: Iterable[float], p: float) -> Optional[float]:
    """Nearest-rank percentile.  Defined for 1..100; returns None on no data, never 0 by accident."""
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    if p <= 1:
        return round(vals[0], 3)
    k = max(1, min(len(vals), int(-(-p * len(vals) // 100))))  # ceil
    return round(vals[k - 1], 3)


def _latency_s(a: Any, b: Any) -> Optional[float]:
    da, db = _dt(a), _dt(b)
    if da is None or db is None:
        return None
    return max(0.0, (db - da).total_seconds())


def _channel(route: str) -> Optional[str]:
    return {"IMMEDIATE": "telegram", "DIGEST": "telegram-digest"}.get(route)


# -------------------------------------------------------------------------------------------------------- classify
def _set(out: dict, stage: str, defect: Optional[str]) -> dict:
    out["stage"] = stage
    out["defect"] = defect
    return out


def classify(row: dict, *, now: Optional[datetime] = None) -> dict:
    """One occurrence row -> the four links it evidences plus the first link that is missing or contradicted.

    ``row`` is the flat mapping :func:`fetch` returns; every field is optional here so a synthetic fixture is a dict
    literal.  Pure: no DB, no clock unless ``now`` is supplied (needed only for age-based classes).
    """
    now = now or datetime.now(timezone.utc)
    route = str(row.get("route_mode") or "").upper()
    notify = bool(row.get("notify"))
    out: dict[str, Any] = {
        "alert_id": row.get("alert_id"),
        "occurrence_id": row.get("occurrence_id"),
        "incident_id": row.get("incident_id"),
        "severity": row.get("severity"),
        "alert_type": row.get("alert_type"),
        "route_mode": route or None,
        "channel": _channel(route),
        "notify": notify,
        "decision_reason": row.get("decision_reason"),
        "intent_priority": row.get("intent_priority"),
        "generated_at": _iso(row.get("recorded_at")),
        "queued_at": None,
        "delivered_at": None,
        "received_at": None,
        "ack_at": None,
        "receipt": None,
        "stage": "generated",
        "defect": None,
        "evidence": None,
    }
    provider_id = row.get("provider_message_id")
    if not notify:
        # The router said no. A provider receipt for the same message still means the operator was reached — and it
        # means the sender acted against the router's decision, which is a contradiction worth naming rather than
        # hiding behind "declined". The incident roll-up decides whether a declined-with-no-receipt row was covered.
        if provider_id:
            out["queued_at"] = _iso(row.get("delivery_created_at"))
            out["delivered_at"] = _iso(row.get("provider_settled_at"))
            out["received_at"] = out["delivered_at"]
            out["receipt"] = str(provider_id)
            out["evidence"] = "communication_events"
            return _set(out, "received", f"router_declined_but_sent:{row.get('decision_reason') or 'unknown'}")
        return _set(out, "generated", f"router_declined:{row.get('decision_reason') or 'unknown'}")

    ack = row.get("event_ack_at") or row.get("delivery_ack_at")
    if ack:
        out["ack_at"] = _iso(ack)

    if route == "DIGEST":
        return _classify_digest(row, out, provider_id)
    if route != "IMMEDIATE":
        return _set(out, "generated", f"no_push_route:{route or 'none'}")
    return _classify_immediate(row, out, now)


def _classify_immediate(row: dict, out: dict, now: datetime) -> dict:
    delivery_id = row.get("delivery_id")
    status = str(row.get("delivery_status") or "").lower()
    reason = str(row.get("delivery_reason") or "")
    msg_id = row.get("delivery_msg_id")
    provider_id = row.get("provider_message_id")
    settled = row.get("provider_settled_at")
    completed = row.get("delivery_completed_at")
    created = row.get("delivery_created_at")
    legacy_delivered = row.get("legacy_delivered")
    out["queued_at"] = _iso(created)

    if delivery_id is None:
        # No intent row at all. If a provider receipt exists anyway, the legacy path sent outside the queue: that is
        # still a delivery, but the queue link the operator asked for is missing.
        if provider_id:
            out["delivered_at"] = _iso(settled)
            out["received_at"] = _iso(settled)
            out["receipt"] = str(provider_id)
            out["evidence"] = "communication_events"
            return _set(out, "received", "queue_stage_missing")
        return _set(out, "generated", "not_queued")

    if status == "sent":
        out["delivered_at"] = _iso(completed) or _iso(created)
        if msg_id or provider_id:
            rid = msg_id or provider_id
            out["receipt"] = str(rid)
            out["received_at"] = _iso(settled) or out["delivered_at"]
            out["evidence"] = "delivery_row" if msg_id else "communication_events"
            return _set(out, "received", None)
        out["evidence"] = "delivery_row"
        return _set(out, "delivered", "delivered_without_receipt")

    if status in ("queued", "claimed"):
        age = _age_min(created, now)
        if status == "claimed" and age is not None and age > CONSUMER_CLAIM_TTL_MIN:
            return _set(out, "queued", "orphaned_claim")
        if age is not None and age > QUEUE_MAX_AGE_MIN:
            return _set(out, "queued", "stuck_in_queue")
        return _set(out, "queued", None)

    if status == "failed":
        return _set(out, "queued", f"send_failed:attempts={row.get('delivery_retry_count') or 0}")

    if status == "abandoned":
        # ``expired:shadow_legacy_owned_delivery`` / ``expired:stale_beyond_ttl`` carry the original after ``|was:``.
        if EXPIRED_SHADOW in reason or SHADOW_OWNS in reason:
            return _legacy_claim(row, out)
        return _set(out, "queued", f"not_delivered:abandoned:{reason or 'no_reason'}")

    if status == "suppressed":
        if SHADOW_UNDELIVERED in reason:
            return _set(out, "queued", "legacy_undelivered_queued")
        if SHADOW_OWNS in reason:
            return _legacy_claim(row, out)
        if "editor_held" in reason or reason.startswith("held"):
            return _set(out, "queued", "held_by_editor")
        return _set(out, "queued", f"not_delivered:suppressed:{reason or 'no_reason'}")

    return _set(out, "queued", f"not_delivered:status:{status or 'none'}")


def _legacy_claim(row: dict, out: dict) -> dict:
    """A row the normalized plane suppressed because the legacy sender owned delivery.

    The suppression reason is the normalized plane's claim ABOUT another sender.  It is not a receipt.  Only a
    provider message id (from the matched communication_events row) is; a ``legacy_delivered: true`` payload flag is
    the sender's self-report and is reported, never counted as received.
    """
    provider_id = row.get("provider_message_id")
    settled = row.get("provider_settled_at")
    if provider_id:
        out["delivered_at"] = _iso(settled)
        out["received_at"] = _iso(settled)
        out["receipt"] = str(provider_id)
        out["evidence"] = "communication_events"
        return _set(out, "received", None)
    if row.get("legacy_delivered") is True:
        out["delivered_at"] = out["queued_at"]
        out["evidence"] = "legacy_self_report"
        return _set(out, "delivered", "receipt_unobservable:legacy_self_report")
    if row.get("legacy_delivered") is False:
        out["evidence"] = "occurrence_payload.legacy_delivered=false"
        return _set(out, "queued", "not_delivered:legacy_reported_failure")
    # ``legacy_delivered`` is null: the sender never reported either way.  The suppression reason is the normalized
    # plane's claim about a different process; the probe does not upgrade it to a receipt and does not downgrade it to
    # a loss.  This is the operator's NOT OBSERVABLE case, and it is reported as such, with the count.
    out["evidence"] = "suppression_reason_only; legacy_delivered not reported"
    return _set(out, "queued", "receipt_unobservable:legacy_delivery_unreported")


def _classify_digest(row: dict, out: dict, provider_id: Any) -> dict:
    queued = row.get("digest_queued_at")
    claimed = row.get("digest_claimed_at")
    included = row.get("digest_included_at")
    out["queued_at"] = _iso(queued)
    if queued is None:
        if provider_id:
            out["delivered_at"] = _iso(row.get("provider_settled_at"))
            out["received_at"] = out["delivered_at"]
            out["receipt"] = str(provider_id)
            out["evidence"] = "communication_events"
            return _set(out, "received", "queue_stage_missing")
        return _set(out, "generated", "not_queued")
    if included is None:
        if claimed is None:
            return _set(out, "queued", "digest_never_claimed")
        return _set(out, "queued", "digest_claimed_never_included")
    # Included in a digest batch.  The batch's provider receipt belongs to the batch, not to this alert.
    out["delivered_at"] = _iso(included)
    out["evidence"] = "digest_queue.included_at"
    return _set(out, "delivered", "receipt_unobservable")


# --------------------------------------------------------------------------------------------------------- summarize
def _break_class(defect: Optional[str]) -> Optional[str]:
    if not defect:
        return None
    head = defect.split(":", 1)[0]
    return head if head in BREAK_CLASSES else "other"


def summarize(rows: list[dict], *, now: Optional[datetime] = None, days: int = 7) -> dict:
    """Classify every occurrence, roll up to incidents, and compute the operator's summary.

    Incident roll-up is the honest unit for "did this real alert reach the operator": a deduped occurrence is fine if
    the same incident was delivered, and an incident with no evidenced delivery anywhere is a break even if each of
    its occurrences looks deliberate in isolation.
    """
    now = now or datetime.now(timezone.utc)
    chains = [classify(r, now=now) for r in rows]

    by_incident: dict[str, list[dict]] = {}
    for c in chains:
        key = c.get("incident_id") or f"occ:{c.get('occurrence_id')}"
        by_incident.setdefault(key, []).append(c)

    incidents: list[dict] = []
    for key, members in by_incident.items():
        evidenced = [m for m in members if m["stage"] == "received" and m["receipt"]]
        self_only = [m for m in members if m["delivered_at"] and not m["receipt"]]
        proven_undelivered = [m for m in members if str(m["defect"] or "").startswith("not_delivered")]
        first_gen = min((m["generated_at"] for m in members if m["generated_at"]), default=None)
        first_del = min((m["delivered_at"] for m in members if m["delivered_at"]), default=None)
        # The earliest *evidenced* receipt, paired with its own timestamp: the incident's delivery time and the message
        # id in the same row must describe the same send, or the table credits one alert with another's receipt.
        first_ev = min((m for m in evidenced if m["delivered_at"]),
                       key=lambda m: _dt(m["delivered_at"]) or datetime.max.replace(tzinfo=timezone.utc),
                       default=None)
        channels = sorted({m["channel"] for m in members if m["channel"]})
        if evidenced:
            evidence_class = "evidenced"
        elif proven_undelivered:
            evidence_class = "proven_undelivered"
        elif self_only:
            evidence_class = "self_report_only"
        elif channels:
            evidence_class = "not_observable"
        else:
            evidence_class = "no_push_route"
        if evidence_class == "evidenced":
            inc_break = None
        elif all(not m["notify"] for m in members):
            inc_break = "deduped_uncovered"
        else:
            inc_break = next((m["defect"] for m in members
                              if _break_class(m["defect"]) not in (None, "router_declined")), "not_observable")
        inc = {
            "incident_id": key,
            "occurrences": len(members),
            "notified": sum(1 for m in members if m["notify"]),
            "severity": members[0].get("severity"),
            "alert_type": members[0].get("alert_type"),
            "channels": channels,
            "generated_at": _iso(first_gen),
            "delivered_at": _iso(first_ev["delivered_at"]) if first_ev else _iso(first_del),
            "latency_s": (_latency_s(first_gen, first_ev["delivered_at"]) if first_ev
                          else _latency_s(first_gen, first_del)),
            "evidence_class": evidence_class,
            "delivered_evidenced": evidence_class == "evidenced",
            "delivered_self_report_only": evidence_class == "self_report_only",
            "delivered_any": evidence_class in ("evidenced", "self_report_only"),
            "receipt": (first_ev["receipt"] if first_ev else None),
            "break": inc_break,
        }
        incidents.append(inc)

        # Every occurrence carries its incident's evidence class, so a row that looks fine alone cannot hide an
        # incident that never produced a receipt.
        for m in members:
            m["incident_evidence_class"] = evidence_class
            m["incident_delivered_evidenced"] = evidence_class == "evidenced"

    push_incidents = [i for i in incidents if i["channels"]]
    evid = [i for i in push_incidents if i["evidence_class"] == "evidenced"]
    self_only = [i for i in push_incidents if i["evidence_class"] == "self_report_only"]
    undelivered = [i for i in push_incidents if i["evidence_class"] == "proven_undelivered"]
    no_receipt = [i for i in push_incidents if not i["delivered_evidenced"]]

    stages = {"generated": len(chains), "queued": 0, "delivered": 0, "received": 0, "acknowledged": 0}
    for c in chains:
        if c["queued_at"]:
            stages["queued"] += 1
        if c["delivered_at"]:
            stages["delivered"] += 1
        if c["received_at"]:
            stages["received"] += 1
        if c["ack_at"]:
            stages["acknowledged"] += 1

    latency: dict[str, dict[str, Any]] = {}
    for ch in ("telegram", "telegram-digest"):
        vals = [i["latency_s"] for i in evid if ch in i["channels"] and i["latency_s"] is not None]
        latency[ch] = {"n": len(vals), "p50_s": percentile(vals, 50), "p95_s": percentile(vals, 95),
                       "max_s": max(vals) if vals else None}

    occ_lat = [x for x in (_latency_s(c["generated_at"], c["received_at"]) for c in chains if c["receipt"])
               if x is not None]

    breaks: dict[str, dict[str, Any]] = {}
    for c in chains:
        cls = _break_class(c["defect"])
        if not cls or cls == "router_declined":
            continue
        slot = breaks.setdefault(cls, {"class": cls, "occurrences": 0, "incidents": set(), "example": None})
        slot["occurrences"] += 1
        slot["incidents"].add(c.get("incident_id") or c.get("occurrence_id"))
        if slot["example"] is None:
            slot["example"] = {
                "alert_id": c["alert_id"], "occurrence_id": c["occurrence_id"], "incident_id": c["incident_id"],
                "severity": c["severity"], "alert_type": c["alert_type"], "route_mode": c["route_mode"],
                "generated_at": c["generated_at"], "queued_at": c["queued_at"], "delivered_at": c["delivered_at"],
                "received_at": c["received_at"], "receipt": c["receipt"], "defect": c["defect"],
                "decision_reason": c["decision_reason"],
            }
    break_list = []
    for slot in sorted(breaks.values(), key=lambda s: (-s["occurrences"], s["class"])):
        slot["incidents"] = len(slot["incidents"])
        break_list.append(slot)

    pct = round(100.0 * len(evid) / len(push_incidents), 1) if push_incidents else None
    return {
        "schema": SCHEMA,
        "generated_at": _iso(now),
        "window_days": days,
        "scope": f"alert_occurrences.severity in {list(SEVERE_SEVERITIES)}",
        "occurrences": {
            "total": len(chains),
            "notify_true": sum(1 for c in chains if c["notify"]),
            "router_declined": sum(1 for c in chains if not c["notify"]),
        },
        "incidents": {
            "total": len(incidents),
            "push_channel": len(push_incidents),
            "delivered_evidenced": len(evid),
            "delivered_self_report_only": len(self_only),
            "delivered_any": len(evid) + len(self_only),
            "proven_undelivered": len(undelivered),
            "no_observable_receipt": len(no_receipt),
            "pct_fully_delivered_evidenced": pct,
            "undelivered_examples": [
                {k: i[k] for k in ("incident_id", "alert_type", "severity", "generated_at",
                                   "evidence_class", "break")}
                for i in no_receipt[:10]
            ],
        },
        "stages": stages,
        "latency_by_channel": latency,
        "occurrence_generated_to_receipt_s": {
            "n": len(occ_lat),
            "p50_s": percentile(occ_lat, 50),
            "p95_s": percentile(occ_lat, 95),
        },
        "break_classes": break_list,
        "receipt_policy": {
            "counts_as_received": "a Telegram/provider message id with a settlement timestamp",
            "not_a_receipt": ["delivery_status='sent' with no message id",
                              "legacy sender's payload.legacy_delivered flag",
                              "digest_queue.included_at (batch, not per alert)"],
            "ack": "communication_events.acknowledged_at; no reader telemetry exists, so ack is NOT OBSERVABLE today",
        },
        "chains": chains,
    }


# -------------------------------------------------------------------------------------------------------------- v2
V2_SQL = """
SELECT e.event_id, e.created_at, e.severity, e.producer, e.message_class, e.acknowledged_at,
       e.subject_key, d.delivery_id, d.channel, d.status, d.sent_at, d.completed_at,
       d.provider_message_id, d.error_taxonomy
  FROM communication_events e
  LEFT JOIN communication_deliveries d ON d.event_id = e.event_id
 WHERE e.created_at >= now() - (%s * interval '1 day')
   AND e.direction = 'OUTBOUND'
   AND e.severity IN ('P0', 'P1', 'critical', 'urgent')
 ORDER BY e.created_at DESC
"""


def summarize_comms_v2(rows: list[dict]) -> dict:
    """The normalized comms pipeline: the only place email/text channels exist.  Same receipt rule as above."""
    events: dict[str, dict] = {}
    for r in rows:
        eid = r.get("event_id")
        ev = events.setdefault(eid, {"event_id": eid, "created_at": r.get("created_at"), "severity": r.get("severity"),
                                     "producer": r.get("producer"), "message_class": r.get("message_class"),
                                     "ack_at": r.get("acknowledged_at"), "deliveries": []})
        if r.get("delivery_id") is not None:
            ev["deliveries"].append(r)
    out: dict[str, dict[str, Any]] = {}
    no_delivery = 0
    for ev in events.values():
        if not ev["deliveries"]:
            no_delivery += 1
            continue
        for d in ev["deliveries"]:
            ch = str(d.get("channel") or "unknown")
            slot = out.setdefault(ch, {"events": 0, "statuses": {}, "with_provider_id": 0,
                                       "receipt_not_observable": 0, "latencies_s": []})
            slot["events"] += 1
            st = str(d.get("status") or "none")
            slot["statuses"][st] = slot["statuses"].get(st, 0) + 1
            if d.get("provider_message_id"):
                slot["with_provider_id"] += 1
            elif st == "SENT":
                slot["receipt_not_observable"] += 1
            lat = _latency_s(ev.get("created_at"), d.get("sent_at") or d.get("completed_at"))
            if lat is not None and st == "SENT":
                slot["latencies_s"].append(lat)
    for slot in out.values():
        lat = slot.pop("latencies_s")
        slot["p50_s"] = percentile(lat, 50)
        slot["p95_s"] = percentile(lat, 95)
    return {"events": len(events), "events_without_delivery_row": no_delivery,
            "by_channel": dict(sorted(out.items())), "receipt": RECEIPT_NOT_OBSERVABLE + " unless with_provider_id > 0"}


# ------------------------------------------------------------------------------------------------------------- db
PROBE_SQL = """
SELECT o.occurrence_id, o.alert_id, o.incident_id, o.recorded_at, o.severity, o.alert_type, o.symbol,
       o.notify, o.decision_reason, o.route_mode, o.logical_destination, o.digest_bucket, o.runtime_mode,
       o.payload->>'intent_priority' AS intent_priority,
       CASE WHEN lower(o.payload->>'legacy_delivered') IN ('true', 'false')
            THEN lower(o.payload->>'legacy_delivered') = 'true' END AS legacy_delivered,
       d.id AS delivery_id, d.delivery_status, d.delivery_reason, d.telegram_message_id AS delivery_msg_id,
       d.created_at AS delivery_created_at, d.completed_at AS delivery_completed_at,
       d.retry_count AS delivery_retry_count,
       q.queued_at AS digest_queued_at, q.claimed_at AS digest_claimed_at, q.included_at AS digest_included_at,
       e.event_id, e.provider_message_id, e.provider_settlement_state, e.provider_settled_at,
       e.created_at AS event_created_at, e.acknowledged_at AS event_ack_at
  FROM alert_occurrences o
  LEFT JOIN LATERAL (
        SELECT x.id, x.delivery_status, x.delivery_reason, x.telegram_message_id, x.created_at, x.completed_at,
               x.retry_count
          FROM alert_notification_deliveries x
         WHERE x.occurrence_id = o.occurrence_id
         ORDER BY x.attempt_seq DESC NULLS LAST, x.id DESC
         LIMIT 1) d ON true
  LEFT JOIN LATERAL (
        SELECT x.queued_at, x.claimed_at, x.included_at
          FROM alert_digest_queue x
         WHERE x.occurrence_id = o.occurrence_id
         ORDER BY x.id DESC
         LIMIT 1) q ON true
  LEFT JOIN LATERAL (
        SELECT ce.event_id, ce.provider_message_id, ce.provider_settlement_state, ce.provider_settled_at,
               ce.created_at, ce.acknowledged_at
          FROM communication_events ce
         WHERE ce.direction = 'OUTBOUND'
           AND ce.created_at BETWEEN o.recorded_at - interval '5 seconds' AND o.recorded_at + interval '90 seconds'
           AND o.payload ? 'message'
           AND o.payload->>'message' IS NOT NULL
           AND right(ce.subject_key, length(left(o.payload->>'message', 48)))
               = left(o.payload->>'message', 48)
         ORDER BY abs(extract(epoch FROM (ce.created_at - o.recorded_at)))
         LIMIT 1) e ON true
 WHERE o.recorded_at >= now() - (%s * interval '1 day')
   AND o.severity = ANY(%s)
 ORDER BY o.recorded_at DESC
"""


DIGEST_SQL = """
SELECT count(*) AS queued_rows, count(claimed_at) AS claimed, count(included_at) AS included,
       min(queued_at) AS oldest_open
  FROM alert_digest_queue
 WHERE queued_at >= now() - (%s * interval '1 day')
"""

DIGEST_ALL_SQL = """
SELECT count(*) AS rows, count(included_at) AS included, min(queued_at) AS oldest, max(queued_at) AS newest
  FROM alert_digest_queue
"""

LEDGER_SQL = """
SELECT severity, count(*) AS rows, count(telegram_message_id) AS with_message_id,
       count(telegram_sent_at) AS with_sent_at, count(acknowledged_at) AS acknowledged
  FROM alert_events
 WHERE created_at >= now() - (%s * interval '1 day')
   AND severity IN ('critical', 'urgent')
 GROUP BY 1 ORDER BY 2 DESC
"""


def summarize_digest(window: dict, alltime: dict) -> dict:
    """The DIGEST channel's own health.  A digest row is included in a batch or it is not; the batch has the receipt."""
    return {
        "window": {k: window.get(k) for k in ("queued_rows", "claimed", "included", "oldest_open")},
        "all_time": {k: alltime.get(k) for k in ("rows", "included", "oldest", "newest")},
        "receipt": "NOT OBSERVABLE per alert; alert_digest_queue.included_at is the batch link only",
    }


def summarize_ledger(rows: list[dict]) -> dict:
    """``alert_events`` is the legacy ledger, not the router.  A row here is a record; a telegram_message_id is a
    receipt.  Reported so 'recorded' is never mistaken for 'dispatched' (registration is not execution)."""
    return {
        "scope": "alert_events created in window, severity critical/urgent",
        "by_severity": {r["severity"]: {k: r.get(k) for k in ("rows", "with_message_id", "with_sent_at",
                                                              "acknowledged")} for r in rows},
        "recorded_without_send": sum(int(r.get("rows") or 0) - int(r.get("with_message_id") or 0) for r in rows),
    }


def _connect(read_only: bool = True):
    """Read-only by construction.  Tries the repo's DB loader (which reads the checkout's .env), then the unix-socket
    names libpq defaults to; the session itself refuses writes either way."""
    import psycopg2  # noqa: PLC0415 -- optional at import time so pure tests need no driver

    conn = None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from config_db_loader import _get_conn  # noqa: PLC0415

        conn = _get_conn()
    except Exception:  # noqa: BLE001 -- a missing .env is not a verdict, the socket may still answer
        kwargs: dict[str, Any] = {"dbname": os.getenv("DB_NAME", "trade_ai"),
                                  "user": os.getenv("DB_USER", "johnclaw"),
                                  "host": os.getenv("DB_HOST", "/var/run/postgresql"),
                                  "connect_timeout": 10}
        if os.getenv("DB_PORT"):
            kwargs["port"] = os.getenv("DB_PORT")
        if os.getenv("DB_PASSWORD"):
            kwargs["password"] = os.getenv("DB_PASSWORD")
        if read_only:
            kwargs["options"] = "-c default_transaction_read_only=on"
        conn = psycopg2.connect(**kwargs)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _dict_rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def fetch(cur, *, days: int = 7) -> list[dict]:
    cur.execute(PROBE_SQL, (days, list(SEVERE_SEVERITIES)))
    return _dict_rows(cur)


def fetch_v2(cur, *, days: int = 7) -> list[dict]:
    cur.execute(V2_SQL, (days,))
    return _dict_rows(cur)


def run(*, days: int = 7, conn=None) -> dict:
    own = conn is None
    try:
        if own:
            conn = _connect(read_only=True)
        with conn.cursor() as cur:
            rows = fetch(cur, days=days)
            v2 = fetch_v2(cur, days=days)
            cur.execute(DIGEST_SQL, (days,))
            digest = _dict_rows(cur)[0]
            cur.execute(DIGEST_ALL_SQL)
            digest_all = _dict_rows(cur)[0]
            cur.execute(LEDGER_SQL, (days,))
            ledger = _dict_rows(cur)
    except Exception as exc:  # noqa: BLE001 -- no DB is a verdict, not a crash
        return {"schema": SCHEMA, "generated_at": _iso(datetime.now(timezone.utc)),
                "window_days": days, "verdict": "UNVERIFIABLE", "error": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        if own and conn is not None:
            conn.close()
    summary = summarize(rows, days=days)
    summary["comms_v2"] = summarize_comms_v2(v2)
    summary["digest_queue"] = summarize_digest(digest, digest_all)
    summary["ledger_alert_events"] = summarize_ledger(ledger)
    lacking = summary["incidents"]["no_observable_receipt"]
    evidenced = summary["incidents"]["delivered_evidenced"]
    if not summary["occurrences"]["total"]:
        summary["verdict"] = "NO_ALERTS_IN_WINDOW"
    elif lacking:
        # C1's acceptance test: every real critical alert shows all four links with a timestamp.  One push-channel
        # incident without a receipt fails it, whether the alert was lost or the receipt is merely unobservable.
        summary["verdict"] = "BROKEN"
    elif evidenced:
        summary["verdict"] = "DELIVERED_WITH_RECEIPTS"
    else:
        summary["verdict"] = "UNVERIFIABLE"
    return summary


# ------------------------------------------------------------------------------------------------------------ table
def _ts(v: Optional[str]) -> str:
    if not v:
        return "-"
    return v.replace("T", " ")[:19]


def table(summary: dict, *, limit: int = 200) -> str:
    chains = summary.get("chains") or []
    lines = [f"{'alert_id':34s} {'occ':>7s} {'sev':8s} {'route':9s} {'generated':19s} {'queued':19s} "
             f"{'delivered':19s} {'received':19s} {'receipt':>10s}  defect"]
    for c in chains[:limit]:
        lines.append(
            f"{str(c['alert_id'])[:34]:34s} {str(c['occurrence_id']):>7s} {str(c['severity'])[:8]:8s} "
            f"{str(c['route_mode'])[:9]:9s} {_ts(c['generated_at']):19s} {_ts(c['queued_at']):19s} "
            f"{_ts(c['delivered_at']):19s} {_ts(c['received_at']):19s} "
            f"{('yes' if c['receipt'] else RECEIPT_NOT_OBSERVABLE[:10]):>10s}  {c['defect'] or '-'}")
    if len(chains) > limit:
        lines.append(f"... {len(chains) - limit} more occurrences (raise --limit)")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--table", action="store_true", help="also print the per-occurrence chain table")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args(argv)
    summary = run(days=args.days)
    # stdout is the operator summary plus, on request, the per-occurrence table; the full chains array (which is what
    # --table renders) goes to --json-out so a caller that pipes stdout is not handed 170 objects first.
    print(json.dumps({k: v for k, v in summary.items() if k != "chains"}, indent=1, sort_keys=True, default=str))
    if args.table:
        print("\n" + table(summary, limit=args.limit))
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=1, sort_keys=True, default=str))
    return 0 if summary.get("verdict") != "UNVERIFIABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
