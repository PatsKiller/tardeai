#!/usr/bin/env python3
"""alert-delivery-queue-hygiene — the IMMEDIATE delivery queue's contract, heal and escalation (LQ-20261107-1607).

PROCESS   n8n lane ``alert-delivery-queue-hygiene`` (config/lane_registry.json), every 5 min, LaneRunReceipt@v2.
CONTRACT  "no IMMEDIATE row of alert_notification_deliveries is still 'queued' more than QUEUE_MAX_AGE_MIN (10) min
          after it was written". Verdicts: OK, DEGRADED (the heal had work: rows expired this run), BROKEN (a
          deliverable row is older than the bound after the heal: the consumer is not draining), UNVERIFIABLE (no DB).
HEAL      deterministic and send-free. A 'queued' row is closed as 'abandoned' with a reason that keeps the original:
            * ``expired:shadow_legacy_owned_delivery|was:<reason>`` — written while the runtime mode was not ACTIVE,
              so the legacy sender already owned (and did) the delivery; it is never sendable;
            * ``expired:stale_beyond_ttl|was:<reason>`` — ACTIVE but older than STALE_TTL_H: an alert that old is
              no longer an interruption worth sending, it is history.
          The table's CHECK constraint has no 'expired' status, so 'abandoned' + an ``expired:`` reason is the
          vocabulary (same rule as scripts/lib/critical_receipts.py).
ESCALATE  BROKEN raises ONE system_health CRITICAL row in alert_events (the path that delivers today), at most one per
          hour. The lane may NOT fix a dead consumer itself: it never sends an operator alert and never re-queues.
          That goes to the ops owner via the system_health alert.

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

# One query classifies every queued row; the occurrence's own runtime_mode says who owned delivery when it was written.
CLASSIFY_SQL = f"""
SELECT d.id,
       CASE
         WHEN COALESCE(o.runtime_mode, '') <> 'ACTIVE' THEN 'shadow'
         WHEN d.created_at < now() - interval '{STALE_TTL_H} hours' THEN 'stale'
         WHEN d.created_at < now() - interval '{QUEUE_MAX_AGE_MIN} minutes' THEN 'stuck'
         ELSE 'fresh'
       END AS klass,
       d.logical_destination,
       d.created_at
  FROM alert_notification_deliveries d
  LEFT JOIN alert_occurrences o ON o.occurrence_id = d.occurrence_id
 WHERE d.delivery_status = 'queued' AND d.route_mode = 'IMMEDIATE'
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
    groups: dict[str, list[int]] = {"shadow": [], "stale": [], "stuck": [], "fresh": []}
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
    if ids["stuck"]:
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

    stuck = summary["counts"]["stuck"]
    return save_alert_event(
        alert_type="system_health",
        raw_text=(f"[{LANE_ID}] BROKEN: {stuck} IMMEDIATE alert(s) still queued after {QUEUE_MAX_AGE_MIN} min "
                  f"(oldest {summary['oldest'].get('stuck')}); the delivery consumer is not draining. "
                  f"The lane does not send; the ops owner restores the consumer."),
        severity="critical",
        source_script=ESCALATION_SOURCE,
        parsed_payload={"kind": "alert_delivery_queue_stuck", "lane_id": LANE_ID, **summary["counts"],
                        "by_destination": summary["by_destination"]},
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
        "contract": f"queued IMMEDIATE row age <= {QUEUE_MAX_AGE_MIN} min",
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
