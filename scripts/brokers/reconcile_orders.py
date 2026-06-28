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


def _match_key(rec: dict) -> tuple:
    return (rec.get("correlation_id"), rec.get("intent_id"), rec.get("broker_order_id"))


def build_reconcile_report(local_intents: list[dict], pilot_rows: list[dict],
                           broker_orders: list[dict], *, max_age_minutes: int = 30) -> dict:
    """Pure broker-truth reconciliation taxonomy (P0-5). No IO — safe to unit test.

    Inputs are plain dicts (DB rows / broker GET results). Produces the full taxonomy:
    stale internal orders, broker orders missing a local intent, local intents missing a
    broker order, partial fills, rejected orders, unknown statuses — each with a
    recommended operator action. Internal state never outruns broker truth here.
    """
    from brokers.order_lifecycle import normalize_broker_status, submit_requires_reconcile

    local_intents = local_intents or []
    pilot_rows = pilot_rows or []
    broker_orders = broker_orders or []

    # Index local rows by the identifiers a broker order could carry.
    local_by_corr = {r.get("correlation_id"): r for r in (local_intents + pilot_rows) if r.get("correlation_id")}
    local_by_intent = {r.get("intent_id"): r for r in (local_intents + pilot_rows) if r.get("intent_id")}
    local_by_boid = {r.get("broker_order_id"): r for r in (local_intents + pilot_rows) if r.get("broker_order_id")}

    out = {
        "stale_internal_orders": [],
        "broker_missing_local": [],
        "local_missing_broker": [],
        "partial_fills": [],
        "rejected_orders": [],
        "unknown_statuses": [],
    }

    # ── Local-side scan: stale submits, local-missing-broker ──
    for r in local_intents + pilot_rows:
        status = r.get("state") or r.get("status") or ""
        age = r.get("age_minutes")
        boid = r.get("broker_order_id")
        if submit_requires_reconcile(status, broker_order_id=boid, age_minutes=age or 0,
                                     max_age_minutes=max_age_minutes):
            out["stale_internal_orders"].append({
                **r, "issue": "stale_submit_no_broker_ack",
                "recommended_action": "GET broker order status before any retry; if no broker "
                                      "order exists, mark ERROR_RECONCILE_REQUIRED (never blind-retry).",
            })
        elif str(status).strip().lower() in ("submit_requested", "submitting", "submitted") and not boid:
            out["local_missing_broker"].append({
                **r, "issue": "local_submit_without_broker_order",
                "recommended_action": "Confirm via broker GET whether the order reached the broker.",
            })

    # ── Broker-side scan: classify each broker order vs local truth ──
    for b in broker_orders:
        norm = normalize_broker_status(b.get("status"), filled_qty=b.get("filled_qty"),
                                       total_qty=b.get("total_qty"))
        local = (local_by_boid.get(b.get("broker_order_id"))
                 or local_by_corr.get(b.get("correlation_id"))
                 or local_by_intent.get(b.get("intent_id")))
        item = {**b, "normalized": norm["normalized"], "lifecycle_state": norm["lifecycle_state"]}
        if local is None:
            out["broker_missing_local"].append({
                **item, "issue": "broker_order_without_local_intent",
                "recommended_action": "Operator review: unexpected broker order — verify origin and "
                                      "cancel if not operator-approved.",
            })
        if norm["normalized"] == "partially_filled":
            out["partial_fills"].append({
                **item, "recommended_action": "Preserve partial fill; decide working-remainder vs cancel."})
        elif norm["normalized"] == "rejected":
            out["rejected_orders"].append({
                **item, "recommended_action": "Surface broker rejection reason to operator; do not retry blindly."})
        elif norm["normalized"] == "unknown":
            out["unknown_statuses"].append({
                **item, "issue": "unmapped_broker_status",
                "recommended_action": "Hold; map status and reconcile manually before any action."})

    counts = {k: len(v) for k, v in out.items()}
    total = sum(counts.values())
    return {
        "ok": True,
        "taxonomy": out,
        "counts": counts,
        "total_findings": total,
        "clean": total == 0,
        "max_age_minutes": max_age_minutes,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _load_local_rows() -> tuple[list[dict], list[dict]]:
    """Read local intent + pilot rows (no broker calls). Returns ([], []) without DB."""
    conn = _conn()
    intents: list[dict] = []
    pilots: list[dict] = []
    if not conn:
        return intents, pilots
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT intent_id, correlation_id, state, broker_order_id,
                      EXTRACT(EPOCH FROM (NOW()-updated_at))/60.0
               FROM broker_order_intents
               WHERE state NOT IN ('FILLED','CANCELLED','REJECTED','EXPIRED')""")
        for iid, corr, state, boid, age in cur.fetchall() or []:
            intents.append({"intent_id": iid, "correlation_id": corr, "state": state,
                            "broker_order_id": boid, "age_minutes": float(age or 0)})
    except Exception:
        pass
    try:
        cur.execute(
            """SELECT id, intent_id, correlation_id, status, broker_order_id, symbol,
                      EXTRACT(EPOCH FROM (NOW()-created_at))/60.0
               FROM schwab_pilot_orders
               WHERE status NOT IN ('filled','canceled','cancelled','rejected','expired')""")
        for rid, iid, corr, status, boid, sym, age in cur.fetchall() or []:
            pilots.append({"pilot_row_id": rid, "intent_id": iid, "correlation_id": corr,
                           "status": status, "broker_order_id": boid, "symbol": sym,
                           "age_minutes": float(age or 0)})
    except Exception:
        pass
    return intents, pilots


def reconcile_once(*, dry_run: bool = True, broker_orders: list[dict] | None = None) -> dict:
    """Reconcile internal rows against broker truth. Safe to run repeatedly.

    ``broker_orders`` may be injected (read-only broker GET results). When omitted it
    defaults to an empty list — this function NEVER issues a broker write and never
    blind-retries; orphan submits are routed to ERROR_RECONCILE_REQUIRED for operator
    review only.
    """
    from brokers.order_lifecycle import transition, OrderState
    stale = find_stale_internal_orders()
    # Full broker-truth taxonomy over local rows (+ any injected read-only broker orders).
    local_intents, pilot_rows = _load_local_rows()
    taxonomy_report = build_reconcile_report(local_intents, pilot_rows, broker_orders or [])
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
        "taxonomy": taxonomy_report["taxonomy"],
        "taxonomy_counts": taxonomy_report["counts"],
        "total_findings": taxonomy_report["total_findings"],
        "clean": taxonomy_report["clean"] and len(stale) == 0,
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
        record_event("reconcile_result", decision="completed",
                     reason=f"stale={len(stale)} findings={taxonomy_report['total_findings']}",
                     component="reconcile_orders",
                     snapshot={"stale_count": len(stale), "dry_run": dry_run,
                               "counts": taxonomy_report["counts"]})
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