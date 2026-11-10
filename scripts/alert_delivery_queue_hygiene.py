#!/usr/bin/env python3
"""alert-delivery-queue-hygiene — the IMMEDIATE delivery queue's contract, heal and escalation (LQ-20261107-1607).

PROCESS   n8n lane ``alert-delivery-queue-hygiene`` (config/lane_registry.json), every 5 min, LaneRunReceipt@v2.
CONTRACT  "no IMMEDIATE row of alert_notification_deliveries is still 'queued' more than QUEUE_MAX_AGE_MIN (10) min
          after it was written, and no row the consumer took is left in a state nobody reads". Verdicts: OK, DEGRADED
          (the heal had work: rows expired this run), BROKEN (the consumer is not draining, or a row is exhausted /
          orphaned / held), UNVERIFIABLE (no DB).
          LQ-20261107-1815 r2 (M3): the contract now covers the consumer's OWN states. The first version classified
          only 'queued', but the consumer moves a row out of 'queued' on its first attempt -- so a row that failed
          three times, a claim abandoned by a crashed worker, and a held critical were all invisible here. That is the
          exact hole that makes a dead consumer silent. Classes: 'exhausted' (failed, out of attempts or past
          STALE_TTL_H), 'retrying' (failed, attempts left: normal, not a verdict), 'orphaned_claim' (claimed past the
          consumer's TTL: a worker died mid-send), 'held' (suppressed with the consumer's own reason: the operator was
          not told) -- each of the last three is BROKEN and escalated.
HEAL      deterministic and send-free, and it never touches a row the consumer is still working. A 'queued' row is
          closed as 'abandoned' with a reason that keeps the original -- failed, claimed and held rows are ESCALATED,
          never expired, because expiring them would destroy the only evidence that a critical was lost:
            * ``expired:shadow_legacy_owned_delivery|was:<reason>`` — written while the runtime mode was not ACTIVE,
              so the legacy sender already owned (and did) the delivery; it is never sendable;
            * ``expired:stale_beyond_ttl|was:<reason>`` — ACTIVE but older than STALE_TTL_H: an alert that old is
              no longer an interruption worth sending, it is history.
          The table's CHECK constraint has no 'expired' status, so 'abandoned' + an ``expired:`` reason is the
          vocabulary (same rule as scripts/lib/critical_receipts.py).
        LQ-20261107-1815: a queued row whose reason starts ``shadow_legacy_undelivered:`` is NOT shadow work. It is a
        CRITICAL alert the legacy router suppressed and the normalized plane queued because nobody received it; it is
        classified like ACTIVE work (fresh / stuck / stale), so the lane can never abandon it at 10 min before its
        consumer has had a chance, and a consumer that stops draining it still raises BROKEN.
ESCALATE  BROKEN raises ONE system_health CRITICAL row in alert_events (the path that delivers today), at most one per
          hour, naming every broken class it found. The lane may NOT fix a dead consumer itself: it never sends an
          operator alert and never re-queues. That goes to the ops owner via the system_health alert.

Dry run is the default and writes nothing (read-only session). ``--apply`` is the only writing path.
MBI_BEHAVIOR = 0: nothing here sizes, orders or touches a broker.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LANE_ID = "alert-delivery-queue-hygiene"
QUEUE_MAX_AGE_MIN = 10
STALE_TTL_H = 6
ESCALATION_SOURCE = "alert_delivery_queue_hygiene.py"
ESCALATION_COOLDOWN_MIN = 60

REASON_SHADOW = "expired:shadow_legacy_owned_delivery"
REASON_STALE = "expired:stale_beyond_ttl"

#: LQ-20261107-1815: a SHADOW row is terminal work-that-nobody-owns ONLY when the legacy path delivered it. A row the
#: occurrence store queued because the legacy send reached nobody (``shadow_legacy_undelivered:``) is real work with a
#: real consumer (``alert_outbox.deliver_critical``), so it must age out like ACTIVE work, never be abandoned at 10 min.
UNDELIVERED_PREFIX = "shadow_legacy_undelivered:"

#: M3: the consumer's own bounds, mirrored from ``alert_outbox`` (CRITICAL_MAX_ATTEMPTS / CRITICAL_CLAIM_TTL_MIN). The
#: lane is a standalone script and does not import the consumer; a test pins the two pairs equal, so a change on one
#: side cannot silently leave the other measuring a stale bound.
CONSUMER_MAX_ATTEMPTS = 3
CONSUMER_CLAIM_TTL_MIN = 15

#: The consumer's "the operator was NOT told" vocabulary. A row in this state is never expired here -- it is escalated.
HELD_REASONS = ("editor_held",)
_HELD_SQL_LIST = ", ".join(f"'{r}'" for r in HELD_REASONS)  # module constants, never user input

#: Classes that mean the queue is not doing its job: each is BROKEN and escalated.
BROKEN_CLASSES = ("stuck", "exhausted", "orphaned_claim", "held")

# One query classifies every IMMEDIATE row the consumer could own -- including the states it leaves behind. The
# occurrence's own runtime_mode says who owned delivery when the row was written, and the row's status/reason says
# whether that owner actually delivered.
CLASSIFY_SQL = f"""
SELECT d.id,
       CASE
         WHEN d.delivery_status = 'failed'
              AND (d.retry_count >= {CONSUMER_MAX_ATTEMPTS}
                   OR d.created_at < now() - interval '{STALE_TTL_H} hours') THEN 'exhausted'
         WHEN d.delivery_status = 'failed' THEN 'retrying'
         WHEN d.delivery_status = 'claimed' THEN 'orphaned_claim'
         WHEN d.delivery_status = 'suppressed' THEN 'held'
         WHEN d.delivery_reason LIKE '{UNDELIVERED_PREFIX}%'
              AND d.created_at < now() - interval '{STALE_TTL_H} hours' THEN 'stale'
         WHEN d.delivery_reason LIKE '{UNDELIVERED_PREFIX}%'
              AND d.created_at < now() - interval '{QUEUE_MAX_AGE_MIN} minutes' THEN 'stuck'
         WHEN d.delivery_reason LIKE '{UNDELIVERED_PREFIX}%' THEN 'fresh'
         WHEN COALESCE(o.runtime_mode, '') <> 'ACTIVE' THEN 'shadow'
         WHEN d.created_at < now() - interval '{STALE_TTL_H} hours' THEN 'stale'
         WHEN d.created_at < now() - interval '{QUEUE_MAX_AGE_MIN} minutes' THEN 'stuck'
         ELSE 'fresh'
       END AS klass,
       d.logical_destination,
       d.created_at
  FROM alert_notification_deliveries d
  LEFT JOIN alert_occurrences o ON o.occurrence_id = d.occurrence_id
 WHERE d.route_mode = 'IMMEDIATE'
   AND (
         d.delivery_status IN ('queued', 'failed')
      OR (d.delivery_status = 'claimed'
          AND (d.claimed_at IS NULL OR d.claimed_at < now() - interval '{CONSUMER_CLAIM_TTL_MIN} minutes'))
      -- Scoped to the consumer's own vocabulary: the legacy 'shadow_legacy_owned_delivery' rows are terminal history
      -- and must not page anyone. A reason this lane does not recognise is left alone rather than guessed at.
      OR (d.delivery_status = 'suppressed'
          AND (d.delivery_reason IN ({_HELD_SQL_LIST})
               OR d.delivery_reason LIKE '{UNDELIVERED_PREFIX}%'))
   )
"""

EXPIRE_SQL = """
UPDATE alert_notification_deliveries
   SET delivery_status = 'abandoned',
       delivery_reason = %s || '|was:' || COALESCE(delivery_reason, ''),
       completed_at = now()
 WHERE id = ANY(%s) AND delivery_status = 'queued'
"""


def _iso(v: Any) -> Optional[str]:
    return v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else None


def classify(rows: list[tuple]) -> dict[str, Any]:
    groups: dict[str, list[int]] = {"shadow": [], "stale": [], "stuck": [], "fresh": [],
                                    "exhausted": [], "retrying": [], "orphaned_claim": [], "held": []}
    oldest: dict[str, Optional[str]] = {}
    by_dest: dict[str, int] = {}
    for rid, klass, dest, created in rows:
        groups.setdefault(klass, []).append(int(rid))
        by_dest[str(dest)] = by_dest.get(str(dest), 0) + 1
        iso = _iso(created)
        if iso and (oldest.get(klass) is None or iso < oldest[klass]):
            oldest[klass] = iso
    return {"ids": groups, "oldest": oldest, "by_destination": dict(sorted(by_dest.items()))}


def verdict_for(plan: dict[str, Any]) -> str:
    ids = plan["ids"]
    if any(ids.get(k) for k in BROKEN_CLASSES):
        return "BROKEN"
    if ids["shadow"] or ids["stale"]:
        return "DEGRADED"
    return "OK"


def _connect(read_only: bool):
    import psycopg2  # noqa: PLC0415 -- optional at import time so the module loads without a driver

    kwargs: dict[str, Any] = {"dbname": os.getenv("DB_NAME", "trade_ai"), "user": os.getenv("DB_USER", "johnclaw"),
                              "host": os.getenv("DB_HOST", "/var/run/postgresql"), "connect_timeout": 10}
    if os.getenv("DB_PORT"):
        kwargs["port"] = os.getenv("DB_PORT")
    if os.getenv("DB_PASSWORD"):
        kwargs["password"] = os.getenv("DB_PASSWORD")
    if read_only:
        kwargs["options"] = "-c default_transaction_read_only=on"
    return psycopg2.connect(**kwargs)


def _escalate_default(summary: dict[str, Any]) -> bool:
    from alert_event_writer import save_alert_event  # noqa: PLC0415

    broken = {k: summary["counts"].get(k, 0) for k in BROKEN_CLASSES if summary["counts"].get(k)}
    detail = ", ".join(f"{k}={v} (oldest {summary['oldest'].get(k)})" for k, v in broken.items())
    return save_alert_event(
        alert_type="system_health",
        raw_text=(f"[{LANE_ID}] BROKEN: delivery rows the consumer did not finish — {detail}. "
                  f"stuck = still queued after {QUEUE_MAX_AGE_MIN} min; exhausted = out of attempts; "
                  f"orphaned_claim = a worker died mid-send; held = the editor held a critical. "
                  f"The lane does not send and does not re-queue; the ops owner restores delivery."),
        severity="critical",
        source_script=ESCALATION_SOURCE,
        parsed_payload={"kind": "alert_delivery_queue_stuck", "lane_id": LANE_ID, **summary["counts"],
                        "broken_classes": sorted(broken), "by_destination": summary["by_destination"]},
    ) is not None


def _recently_escalated(cur) -> bool:
    cur.execute(
        "SELECT 1 FROM alert_events WHERE source_script = %s AND alert_type = 'system_health' "
        f"AND created_at > now() - interval '{ESCALATION_COOLDOWN_MIN} minutes' LIMIT 1",
        (ESCALATION_SOURCE,),
    )
    return cur.fetchone() is not None


def run(*, apply: bool, conn=None, escalate: Callable[[dict[str, Any]], bool] = _escalate_default) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    own = conn is None
    try:
        if own:
            conn = _connect(read_only=not apply)
        with conn.cursor() as cur:
            cur.execute(CLASSIFY_SQL)
            plan = classify(cur.fetchall())
    except Exception as exc:  # noqa: BLE001 -- no DB is a verdict, not a crash
        return {"lane_id": LANE_ID, "mode": "apply" if apply else "dry_run", "started_at": started,
                "verdict": "UNVERIFIABLE", "error": f"{type(exc).__name__}"[:120], "expired": 0, "escalated": False}

    counts = {k: len(v) for k, v in plan["ids"].items()}
    summary: dict[str, Any] = {
        "lane_id": LANE_ID, "mode": "apply" if apply else "dry_run", "started_at": started,
        "contract": (f"queued IMMEDIATE row age <= {QUEUE_MAX_AGE_MIN} min; no failed row out of attempts, no claim "
                     f"older than {CONSUMER_CLAIM_TTL_MIN} min, no held critical"),
        "verdict": verdict_for(plan), "counts": counts, "oldest": plan["oldest"],
        "by_destination": plan["by_destination"],
        "would_expire": {REASON_SHADOW: counts["shadow"], REASON_STALE: counts["stale"]},
        "expired": 0, "escalated": False, "sends": 0,
    }
    if not apply:
        if own:
            conn.close()
        return summary

    expired = 0
    try:
        with conn.cursor() as cur:
            for reason, ids in ((REASON_SHADOW, plan["ids"]["shadow"]), (REASON_STALE, plan["ids"]["stale"])):
                if ids:
                    cur.execute(EXPIRE_SQL, (reason, ids))
                    expired += cur.rowcount
            recently = _recently_escalated(cur) if summary["verdict"] == "BROKEN" else False
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if own:
            conn.close()
    summary["expired"] = expired
    if summary["verdict"] == "BROKEN" and not recently:
        summary["escalated"] = bool(escalate(summary))
    summary["escalation_suppressed_cooldown"] = summary["verdict"] == "BROKEN" and recently
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="expire rows and escalate (default: dry run, read-only)")
    args = ap.parse_args(argv)
    summary = run(apply=args.apply)
    print(json.dumps(summary, indent=1, sort_keys=True))
    if args.apply:
        try:
            from scripts.lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415
        except ImportError:
            from lib.lane_last_receipt import write_lane_receipt  # type: ignore[no-redef]  # noqa: PLC0415
        ok = summary["verdict"] in ("OK", "DEGRADED")
        attempted = sum(summary.get("counts", {}).values())
        write_lane_receipt(
            LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=summary["started_at"], script=__file__,
            summary={k: summary.get(k) for k in ("verdict", "counts", "expired", "escalated", "oldest")},
            error=None if ok else summary.get("error") or "queue_not_draining",
            produced_count=summary["expired"], attempted_count=attempted,
            empty_reason=None if summary["expired"] else "nothing_due",
        )
    return 0 if summary["verdict"] in ("OK", "DEGRADED") else 1


if __name__ == "__main__":
    sys.exit(main())
