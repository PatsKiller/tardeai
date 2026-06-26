#!/usr/bin/env python3
"""Safe repeatable broker order reconciliation — orphan detection and stale state repair."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = ROOT / "data" / "runtime"


def _conn():
    try:
        from db_adapter import _get_conn
        return _get_conn()
    except Exception:
        return None


def find_stale_internal_orders(*, max_age_minutes: int = 30) -> list[dict]:
    """SUBMIT_REQUESTED / OPERATOR_APPROVED without broker ack beyond threshold."""
    conn = _conn()
    if not conn:
        return []
    cur = conn.cursor()
    out = []
    try:
        cur.execute(
            """SELECT intent_id, correlation_id, state, updated_at
               FROM broker_order_intents
               WHERE state IN ('SUBMIT_REQUESTED','OPERATOR_APPROVED','WORKING')
                 AND updated_at < NOW() - INTERVAL '%s minutes'""",
            (max_age_minutes,),
        )
        for iid, corr, state, updated in cur.fetchall() or []:
            out.append({"intent_id": iid, "correlation_id": corr, "state": state,
                        "updated_at": str(updated), "issue": "stale_internal_state"})
    except Exception:
        pass
    try:
        cur.execute(
            """SELECT id, intent_id, correlation_id, status, broker_order_id, created_at
               FROM schwab_pilot_orders
               WHERE status IN ('submitting','submitted') AND broker_order_id IS NULL
                 AND created_at < NOW() - INTERVAL '%s minutes'""",
            (max_age_minutes,),
        )
        for rid, iid, corr, status, boid, created in cur.fetchall() or []:
            out.append({"pilot_row_id": rid, "intent_id": iid, "correlation_id": corr,
                        "status": status, "created_at": str(created),
                        "issue": "submit_without_broker_ack"})
    except Exception:
        pass
    return out


def reconcile_once(*, dry_run: bool = True) -> dict:
    """Reconcile internal rows against broker truth. Safe to run repeatedly."""
    from brokers.order_lifecycle import transition, OrderState
    stale = find_stale_internal_orders()
    actions = []
    conn = _conn()
    for row in stale:
        issue = row.get("issue")
        if issue == "submit_without_broker_ack":
            ev = transition("SUBMIT_REQUESTED", OrderState.ERROR_RECONCILE_REQUIRED.value,
                            correlation_id=row.get("correlation_id"),
                            reason="orphan_submit_no_broker_ack")
            actions.append({**row, "action": ev})
            if not dry_run and conn and ev.get("ok"):
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """UPDATE schwab_pilot_orders SET status='error_reconcile_required', updated_at=NOW()
                           WHERE id=%s""",
                        (row.get("pilot_row_id"),),
                    )
                    conn.commit()
                except Exception:
                    pass
        elif issue == "stale_internal_state":
            actions.append({**row, "action": {"ok": True, "note": "flagged_for_operator_review"}})
    report = {
        "ok": True,
        "dry_run": dry_run,
        "stale_count": len(stale),
        "actions": actions,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"reconcile_orders_{dt.date.today().isoformat()}.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        report["report_path"] = str(path)
    except Exception:
        pass
    try:
        from audit_ledger import record_event
        record_event("reconcile_result", decision="completed", reason=f"stale={len(stale)}",
                     component="reconcile_orders", snapshot={"stale_count": len(stale), "dry_run": dry_run})
    except Exception:
        pass
    return report


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    print(json.dumps(reconcile_once(dry_run=not args.apply), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())