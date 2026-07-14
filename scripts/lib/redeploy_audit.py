"""redeploy_audit — governance lineage for redeploy events/plans (Phase 15).

Writers are fail-soft (an audit failure must never break the action being audited)
but the READ side is a governance surface: an event with plan versions must never
show an empty audit trail. Advisory only."""
from __future__ import annotations

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION = PROJECT_ROOT / "migrations" / "2026_07_21_redeploy_audit_log.sql"


def ensure_audit_schema(cur) -> None:
    try:
        from lib.redeploy_schema import run_migrations_once
    except ImportError:
        from redeploy_schema import run_migrations_once
    run_migrations_once(cur, "audit_log", (MIGRATION,))


def audit_log(cur, event_id: int, action: str, *, plan_id: int | None = None,
              plan_version: int | None = None, actor: str = "system",
              prior_value: str | None = None, new_value: str | None = None,
              reason: str | None = None, correlation_id: str | None = None,
              inferred: bool = False, occurred_at=None) -> None:
    """Record one lineage row. Fail-soft: never raises into the audited action."""
    try:
        ensure_audit_schema(cur)
        cur.execute(
            """INSERT INTO redeploy_audit_log
               (deploy_event_id, plan_id, plan_version, action, actor, prior_value,
                new_value, reason, correlation_id, inferred, occurred_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (int(event_id), plan_id, plan_version, action[:80], actor[:60],
             (prior_value or "")[:400] or None, (new_value or "")[:400] or None,
             (reason or "")[:400] or None, correlation_id, bool(inferred), occurred_at),
        )
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass


def list_audit(cur, event_id: int, *, limit: int = 200) -> list[dict[str, Any]]:
    ensure_audit_schema(cur)
    cur.execute(
        """SELECT id, deploy_event_id, plan_id, plan_version, action, actor, prior_value,
                  new_value, reason, correlation_id, inferred, occurred_at, created_at
           FROM redeploy_audit_log WHERE deploy_event_id=%s
           ORDER BY COALESCE(occurred_at, created_at) DESC, id DESC LIMIT %s""",
        (int(event_id), int(limit)),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def backfill_event_lineage(cur, event_id: int) -> dict[str, Any]:
    """One-time reconstruction from surviving evidence. Provable rows carry real
    timestamps; the rest are inferred=TRUE / INFERRED_FROM_CURRENT_STATE."""
    ensure_audit_schema(cur)
    cur.execute("SELECT COUNT(*) FROM redeploy_audit_log WHERE deploy_event_id=%s AND action='event_created'",
                (event_id,))
    if cur.fetchone()[0]:
        return {"ok": True, "skipped": "already backfilled"}

    cur.execute("""SELECT symbol, account, created_at, updated_at, sold_at, txn_ref,
                          reconciliation_status, locked_plan_id, locked_plan_version, status
                   FROM deploy_events WHERE id=%s""", (event_id,))
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "event not found"}
    cols = [d[0] for d in cur.description]
    e = dict(zip(cols, row))
    n = 0

    audit_log(cur, event_id, "event_created", actor="deploy_detect",
              new_value=f"{e['symbol']} {e['account']} sold {e['sold_at']}",
              reason=f"source txn {e.get('txn_ref') or 'n/a'}", occurred_at=e["created_at"])
    n += 1
    if str(e.get("reconciliation_status") or "") in ("verified", "settled"):
        audit_log(cur, event_id, "settlement_verified", actor="system",
                  new_value=e["reconciliation_status"],
                  reason="INFERRED_FROM_CURRENT_STATE — exact verification time not recorded",
                  inferred=True)
        n += 1

    cur.execute("""SELECT version, MIN(created_at), COUNT(*), MAX(generator_version)
                   FROM deploy_plans WHERE deploy_event_id=%s GROUP BY version ORDER BY version""",
                (event_id,))
    for ver, ts, cnt, gen in cur.fetchall():
        audit_log(cur, event_id, "plan_version_generated", plan_version=ver,
                  actor="deploy_recompute", new_value=f"{cnt} archetype plans (generator {gen})",
                  occurred_at=ts)
        n += 1
    if e.get("locked_plan_id"):
        audit_log(cur, event_id, "plan_locked", plan_id=e["locked_plan_id"],
                  plan_version=e.get("locked_plan_version"), actor="operator",
                  reason="INFERRED_FROM_CURRENT_STATE", inferred=True)
        n += 1

    # fixture cleanup is documented history (CHANGELOG 2026-07-14) — provable action, imprecise time
    if event_id == 144:
        audit_log(cur, event_id, "fixture_cleanup_executed", actor="operator+system",
                  prior_value="3 quarantined phase_e test fills + test plan-lock",
                  new_value="deleted; event unlocked; ledger/bus cleaned",
                  reason="operator-approved cleanup 2026-07-14 (see CHANGELOG)", inferred=True)
        n += 1

    # oversight rows: read under a savepoint so a schema surprise can never roll
    # back the lineage rows already written in this transaction
    try:
        cur.execute("SAVEPOINT audit_backfill_oversight")
        cur.execute("""SELECT id, verdict, lane, ran_at FROM deploy_oversight_runs
                       WHERE deploy_event_id=%s ORDER BY id""", (event_id,))
        runs = cur.fetchall()
        cur.execute("RELEASE SAVEPOINT audit_backfill_oversight")
        for oid, verdict, lane, ts in runs:
            audit_log(cur, event_id, "oversight_run", actor=f"oversight:{lane}",
                      new_value=f"run #{oid} verdict={verdict}", occurred_at=ts)
            n += 1
    except Exception:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT audit_backfill_oversight")
        except Exception:
            pass

    return {"ok": True, "rows_written": n}
