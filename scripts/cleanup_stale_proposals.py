#!/usr/bin/env python3
"""cleanup_stale_proposals.py — Reject stale/blocked paper proposals during market hours.

Rejects proposals that are:
- PENDING/APPROVED older than 24 hours
- BLOCKED for more than 4 hours
- MISSING_DATA for more than 48 hours

PAPER ONLY. Does not touch broker, execution, or holdings.

Usage:
    .venv/bin/python scripts/cleanup_stale_proposals.py --dry-run
    .venv/bin/python scripts/cleanup_stale_proposals.py --apply
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [cleanup] {msg}", flush=True)


def sweep_approved_paper_test_lifecycle(cur, conn, apply: bool) -> dict:
    """Normalize terminal APPROVED_FOR_PAPER_TEST rows and re-queue drift revalidation cases."""
    stats = {"executed_to_approved": 0, "requeued_revalidation": 0, "expired_terminal": 0,
             "enrichment_cleared": 0}
    cur.execute("""
        SELECT id, symbol, paper_submit_state, execution_eligibility_status,
               execution_eligibility_reason, expires_at
        FROM paper_trade_proposals
        WHERE status = 'APPROVED_FOR_PAPER_TEST'
    """)
    rows = cur.fetchall()
    for pid, sym, submit_state, elig, elig_reason, expires_at in rows:
        cur.execute("""
            SELECT status, lifecycle_state, broker_order_id
            FROM paper_trades WHERE proposal_id = %s ORDER BY id DESC LIMIT 1
        """, (pid,))
        trade = cur.fetchone()

        if elig == 'NEEDS_REVALIDATION' or submit_state in ('VALIDATING', 'NOT_SUBMITTED'):
            if apply:
                cur.execute("""
                    UPDATE paper_trade_proposals
                    SET status = 'PENDING',
                        material_change_pending_approval = true,
                        approved_pending_recheck = true,
                        execution_recheck_required = true,
                        paper_submit_state = NULL,
                        paper_trade_id = NULL,
                        approved_at = NULL,
                        action_label = COALESCE(action_label, 'Requeued: execution revalidation'),
                        updated_at = NOW()
                    WHERE id = %s AND status = 'APPROVED_FOR_PAPER_TEST'
                """, (pid,))
                if cur.rowcount:
                    stats["requeued_revalidation"] += 1
                    log(f"  #{pid} {sym} requeued (revalidation: {elig_reason or submit_state})")
            else:
                stats["requeued_revalidation"] += 1
                log(f"  [dry-run] #{pid} {sym} would requeue (revalidation)")
            continue

        if submit_state == 'EXECUTED' and trade:
            t_status, t_lifecycle, broker_oid = trade
            if t_status in ('closed', 'superseded_by_fill') or t_lifecycle == 'closed' or broker_oid:
                if apply:
                    cur.execute("""
                        UPDATE paper_trade_proposals
                        SET status = 'APPROVED', updated_at = NOW()
                        WHERE id = %s AND status = 'APPROVED_FOR_PAPER_TEST'
                    """, (pid,))
                    if cur.rowcount:
                        stats["executed_to_approved"] += 1
                        log(f"  #{pid} {sym} → APPROVED (paper trade completed)")
                else:
                    stats["executed_to_approved"] += 1
                continue

        if expires_at and submit_state in ('BLOCKED', None) and str(elig or '') != 'NEEDS_REVALIDATION':
            if apply:
                cur.execute("""
                    UPDATE paper_trade_proposals
                    SET status = 'EXPIRED', updated_at = NOW()
                    WHERE id = %s AND status = 'APPROVED_FOR_PAPER_TEST'
                      AND expires_at < NOW()
                """, (pid,))
                if cur.rowcount:
                    stats["expired_terminal"] += 1
                    log(f"  #{pid} {sym} → EXPIRED (past expires_at)")
            elif expires_at:
                stats["expired_terminal"] += 1

    return stats


def sweep_stale_enrichment_in_progress(cur, conn, apply: bool, *, stale_minutes: int = 30) -> dict:
    """Clear IN_PROGRESS on terminal rows; reset stuck active rows so enrichment cron can retry."""
    stats = {"terminal_cleared": 0, "active_reset": 0}
    stale_m = max(5, int(stale_minutes))
    cur.execute(
        f"""SELECT COUNT(*) FROM paper_trade_proposals
            WHERE enrichment_status = 'IN_PROGRESS'
              AND status IN ('EXPIRED', 'REJECTED', 'APPROVED', 'RISK_BLOCKED')"""
    )
    terminal_n = int(cur.fetchone()[0] or 0)
    cur.execute(
        f"""SELECT COUNT(*) FROM paper_trade_proposals
            WHERE enrichment_status = 'IN_PROGRESS'
              AND status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')
              AND COALESCE(enrichment_last_attempt_at, updated_at)
                  < NOW() - INTERVAL '{stale_m} minutes'"""
    )
    active_n = int(cur.fetchone()[0] or 0)
    if not apply:
        stats["terminal_cleared"] = terminal_n
        stats["active_reset"] = active_n
        return stats
    if terminal_n:
        cur.execute("""
            UPDATE paper_trade_proposals
            SET enrichment_status = 'COMPLETE', updated_at = NOW()
            WHERE enrichment_status = 'IN_PROGRESS'
              AND status IN ('EXPIRED', 'REJECTED', 'APPROVED', 'RISK_BLOCKED')
        """)
        stats["terminal_cleared"] = cur.rowcount
    if active_n:
        cur.execute(
            f"""UPDATE paper_trade_proposals
                SET enrichment_status = NULL, updated_at = NOW()
                WHERE enrichment_status = 'IN_PROGRESS'
                  AND status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')
                  AND COALESCE(enrichment_last_attempt_at, updated_at)
                      < NOW() - INTERVAL '{stale_m} minutes'"""
        )
        stats["active_reset"] = cur.rowcount
    if stats["terminal_cleared"] or stats["active_reset"]:
        conn.commit()
    return stats


def run_pipeline_sweep(cur, conn, apply: bool, *, stale_minutes: int = 30) -> dict:
    """Lifecycle normalize + enrichment IN_PROGRESS sweep — no drift or 24h stale reject."""
    lifecycle = sweep_approved_paper_test_lifecycle(cur, conn, apply=apply)
    enrich = sweep_stale_enrichment_in_progress(cur, conn, apply=apply, stale_minutes=stale_minutes)
    lifecycle["enrichment_terminal_cleared"] = enrich.get("terminal_cleared", 0)
    lifecycle["enrichment_active_reset"] = enrich.get("active_reset", 0)
    return lifecycle


def drift_pass(cur, conn, apply: bool) -> int:
    """PRICE DRIFT (2026-07-03, mirrors the watchlist plan-drift rule): a PENDING proposal whose
    live price is >PROPOSAL_DRIFT_PCT from proposed_entry has stale levels — filling it would be
    far from the analyzed setup. Age floor 4h so normal intraday movement doesn't churn fresh
    proposals. Quote source: finviz_quote_cache.json (the cache the repricer maintains)."""
    import json as _json
    import os as _os
    drift_pct = float(_os.environ.get("PROPOSAL_DRIFT_PCT", "15"))
    try:
        qc = _json.loads((PROJ / "data" / "portfolios" / "state" / "finviz_quote_cache.json").read_text())
        quotes = {k.upper(): v.get("price") for k, v in qc.items()
                  if isinstance(v, dict) and not str(k).startswith("_")}
    except Exception:
        return 0
    if not quotes:
        return 0
    cur.execute("""
        SELECT id, symbol, proposed_entry, created_at
        FROM paper_trade_proposals
        WHERE status = 'PENDING' AND paper_trade_id IS NULL
          AND created_at < NOW() - INTERVAL '4 hours'
          AND proposed_entry IS NOT NULL AND proposed_entry > 0
    """)
    drifted = []
    for pid, sym, entry, created in cur.fetchall():
        try:
            px = float(quotes.get(str(sym).upper()) or 0)
            entry_f = float(entry)
        except (TypeError, ValueError):
            continue
        if px <= 0 or entry_f <= 0:
            continue
        pct = abs(px - entry_f) / entry_f * 100
        if pct > drift_pct:
            drifted.append((pid, sym, entry_f, px, pct))
    if not drifted:
        return 0
    log(f"Price-drift pass ({drift_pct:.0f}% threshold): {len(drifted)} PENDING proposal(s)")
    for pid, sym, entry_f, px, pct in drifted:
        log(f"  #{pid} {sym} entry {entry_f:.2f} vs live {px:.2f} ({pct:.0f}%) → price_drift")
    if not apply:
        return len(drifted)
    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'REJECTED', action_state = 'REJECTED',
            action_label = 'Auto-rejected: price drifted from proposed entry',
            updated_at = NOW()
        WHERE id = ANY(%s) AND status = 'PENDING' AND paper_trade_id IS NULL
    """, ([d[0] for d in drifted],))
    conn.commit()
    return len(drifted)

def main():
    p = argparse.ArgumentParser(description="Reject stale/blocked paper proposals")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument(
        "--pipeline-sweep",
        action="store_true",
        help="Only normalize APPROVED_FOR_PAPER_TEST + clear stale enrichment IN_PROGRESS",
    )
    p.add_argument(
        "--in-progress-stale-minutes",
        type=int,
        default=30,
        help="Minutes before an active IN_PROGRESS row is reset (pipeline-sweep)",
    )
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    if args.pipeline_sweep:
        sweep = run_pipeline_sweep(
            cur, conn, apply=args.apply, stale_minutes=args.in_progress_stale_minutes,
        )
        mode = "APPLY" if args.apply else "DRY RUN"
        log(f"{mode} pipeline sweep: {sweep}")
        conn.close()
        return

    # Find stale proposals. Never sweep an APPROVED row that already produced a paper trade
    # (it would flip an executed proposal to REJECTED while its paper_trades row stays open).
    cur.execute("""
        SELECT id, symbol, status, action_state, created_at, NOW() - created_at AS age
        FROM paper_trade_proposals
        WHERE status IN ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND paper_trade_id IS NULL
          AND (
            created_at < NOW() - INTERVAL '24 hours'
            OR (action_state = 'BLOCKED' AND created_at < NOW() - INTERVAL '4 hours')
            OR (action_state = 'MISSING_DATA' AND created_at < NOW() - INTERVAL '48 hours')
          )
        ORDER BY created_at
    """)
    stale = cur.fetchall()

    drift_n = drift_pass(cur, conn, apply=args.apply)
    if drift_n and args.dry_run:
        log(f"DRY RUN — {drift_n} drift rejection(s) not applied.")

    lifecycle = sweep_approved_paper_test_lifecycle(cur, conn, apply=args.apply)
    enrich = sweep_stale_enrichment_in_progress(
        cur, conn, apply=args.apply, stale_minutes=args.in_progress_stale_minutes,
    )
    lifecycle["enrichment_terminal_cleared"] = enrich.get("terminal_cleared", 0)
    lifecycle["enrichment_active_reset"] = enrich.get("active_reset", 0)
    if any(lifecycle.values()):
        log(f"APPROVED_FOR_PAPER_TEST lifecycle: {lifecycle}")

    if not stale:
        log("No stale paper proposals to clean up.")
        conn.close()
        try:
            sys.path.insert(0, str(PROJ / "scripts"))
            import broker_queue_hygiene as bqh
            sweep = bqh.sweep_broker_queue(dry_run=False, refresh_quotes=True)
            log(
                f"Broker queue hygiene: checked={sweep.get('checked')} "
                f"expired={sweep.get('expired', sweep.get('would_expire', 0))} "
                f"rejected={sweep.get('rejected', sweep.get('would_reject', 0))}"
            )
        except Exception as e:
            log(f"Broker queue hygiene skipped: {e}")
        return

    log(f"Found {len(stale)} stale proposals:")
    for row in stale:
        pid, sym, status, action, created, age = row
        reason = "blocked" if action == "BLOCKED" else ("missing_data" if action == "MISSING_DATA" else "stale_24h")
        log(f"  #{pid} {sym} [{status}/{action}] age={age} → {reason}")

    if args.dry_run:
        log("DRY RUN — no changes made.")
        conn.close()
        return

    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'REJECTED',
            action_state = 'REJECTED',
            action_label = CASE
              WHEN action_state = 'BLOCKED' THEN 'Auto-rejected: blocked and stale'
              WHEN action_state = 'MISSING_DATA' THEN 'Auto-rejected: missing data and stale'
              ELSE 'Auto-rejected: older than 24h'
            END,
            updated_at = NOW()
        WHERE status IN ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND paper_trade_id IS NULL
          AND (
            created_at < NOW() - INTERVAL '24 hours'
            OR (action_state = 'BLOCKED' AND created_at < NOW() - INTERVAL '4 hours')
            OR (action_state = 'MISSING_DATA' AND created_at < NOW() - INTERVAL '48 hours')
          )
        RETURNING id, symbol
    """)
    rejected = cur.fetchall()
    conn.commit()
    conn.close()

    log(f"Rejected {len(rejected)} stale proposals.")
    for pid, sym in rejected:
        log(f"  #{pid} {sym}")

    try:
        sys.path.insert(0, str(PROJ / "scripts"))
        import broker_queue_hygiene as bqh
        sweep = bqh.sweep_broker_queue(dry_run=False, refresh_quotes=True)
        log(
            f"Broker queue hygiene: checked={sweep.get('checked')} "
            f"expired={sweep.get('expired', sweep.get('would_expire', 0))} "
            f"rejected={sweep.get('rejected', sweep.get('would_reject', 0))}"
        )
    except Exception as e:
        log(f"Broker queue hygiene skipped: {e}")

if __name__ == "__main__":
    main()
