#!/usr/bin/env python3
"""lifecycle_event_writer.py — Traceability spine for ATM lifecycle.

Writes lifecycle_events rows linking the full trade chain:
  candidate → signal → proposal → decision → trade → stop → exit → TCA → learning

Usage:
    python scripts/lifecycle_event_writer.py --dry-run
    python scripts/lifecycle_event_writer.py --backfill --dry-run
    python scripts/lifecycle_event_writer.py --backfill --apply
"""
import argparse, hashlib, json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [lifecycle] %(message)s")
log = logging.getLogger("lifecycle_event_writer")

LOG_FILE = PROJECT_ROOT / "logs" / "lifecycle_event_writer.log"

STRATEGY_FAMILIES = {
    "momentum_scalp": "momentum", "gap_and_go": "momentum",
    "swing_breakout": "swing", "swing_trade": "swing", "earnings_catalyst": "swing",
    "earnings_pre_buildup": "swing", "earnings_post_momentum": "swing",
    "fib_retracement_bounce": "swing", "speculative_growth": "swing",
    "dividend_growth_compounder": "income", "reit_income": "income",
    "high_yield_income_bdc": "income", "bond_income": "income",
    "covered_call_income": "income", "income_add": "income",
    "international_dividend": "income",
    "core_growth_compounder": "position", "core_index": "position",
    "defense_thesis": "position", "tax_loss_harvest": "position",
    "sector_rotation": "position", "recovery_watch": "income",
    "cash_or_stable": "position",
}


def _get_conn():
    try:
        from db_adapter import _get_conn as gc
        return gc()
    except Exception:
        return None


def generate_lifecycle_id(symbol, strategy_id, source_id):
    """Generate a deterministic lifecycle ID from key fields."""
    raw = f"{symbol}:{strategy_id}:{source_id}"
    return f"lc-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def write_event(conn, lifecycle_id, stage, event_type, status=None, symbol=None,
                strategy_id=None, signal_id=None, proposal_id=None, decision_id=None,
                paper_trade_id=None, execution_quality_id=None, source_script=None,
                source_table=None, source_pk=None, payload=None, event_ts=None,
                dry_run=False, **kwargs):
    """Write a single lifecycle event. Never fails the trading path."""
    try:
        family = STRATEGY_FAMILIES.get(strategy_id or "", "unknown")
        ts = event_ts or datetime.now(timezone.utc)

        if dry_run:
            log.info(f"[DRY] {stage}/{event_type} {symbol} {strategy_id} lc={lifecycle_id}")
            return True

        cur = conn.cursor()
        cur.execute("""INSERT INTO lifecycle_events
            (lifecycle_id, event_ts, stage, event_type, status, symbol, strategy_id,
             strategy_family, signal_id, proposal_id, decision_id, paper_trade_id,
             execution_quality_id, source_script, source_table, source_pk, payload,
             agent_owner, raci_responsible, paper_order_id, broker_order_id, stop_order_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [lifecycle_id, ts, stage, event_type, status, symbol, strategy_id,
             family, signal_id, proposal_id, decision_id, paper_trade_id,
             execution_quality_id, source_script, source_table, source_pk,
             json.dumps(payload) if payload else None,
             kwargs.get("agent_owner"), kwargs.get("raci_responsible"),
             kwargs.get("paper_order_id"), kwargs.get("broker_order_id"),
             kwargs.get("stop_order_id")])
        conn.commit()
        return True
    except Exception as e:
        log.warning(f"Event write failed (non-fatal): {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            with open(LOG_FILE, "a") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} WRITE_FAIL {stage}/{event_type} {symbol} {e}\n")
        except Exception:
            pass
        return False


def backfill(conn, dry_run=True):
    """Backfill lifecycle_events from existing tables. Read-only on trading tables."""
    cur = conn.cursor()
    stats = {"proposals": 0, "trades": 0, "tca": 0, "skipped": 0}

    # 1. Backfill from paper_trade_proposals
    log.info("Backfilling proposals...")
    cur.execute("""SELECT id, symbol, strategy_id, source_signal_id, signal_score,
                          signal_decision, created_at
                   FROM paper_trade_proposals ORDER BY id""")
    for row in cur.fetchall():
        pid, sym, sid, sig_id, score, decision, created = row
        lc_id = generate_lifecycle_id(sym, sid, f"proposal-{pid}")

        # Check if already backfilled
        cur2 = conn.cursor()
        cur2.execute("SELECT 1 FROM lifecycle_events WHERE lifecycle_id=%s AND stage='proposal' LIMIT 1", [lc_id])
        if cur2.fetchone():
            stats["skipped"] += 1
            continue

        # Signal event
        if sig_id:
            write_event(conn, lc_id, "signal", "signal_created", status="scored",
                        symbol=sym, strategy_id=sid, signal_id=str(sig_id),
                        source_script="trade_ai_orchestrator.py", source_table="strategy_signals",
                        source_pk=str(sig_id), payload={"score": float(score) if score else None},
                        event_ts=created, dry_run=dry_run)

        # Proposal event
        write_event(conn, lc_id, "proposal", "proposal_created", status=decision or "pending",
                    symbol=sym, strategy_id=sid, signal_id=str(sig_id) if sig_id else None,
                    proposal_id=str(pid), source_script="auto_proposal_generator.py",
                    source_table="paper_trade_proposals", source_pk=str(pid),
                    event_ts=created, dry_run=dry_run)
        stats["proposals"] += 1

    # 2. Backfill from paper_trades
    log.info("Backfilling trades...")
    cur.execute("""SELECT id, symbol, strategy_id, signal_id, entry_price, entry_time,
                          stop_loss, exit_price, exit_time, exit_reason, pnl, account
                   FROM paper_trades ORDER BY id""")
    for row in cur.fetchall():
        tid, sym, sid, sig_id, entry, etime, stop, exit_p, exit_t, exit_r, pnl, acct = row
        lc_id = generate_lifecycle_id(sym, sid, f"trade-{tid}")

        cur2 = conn.cursor()
        cur2.execute("SELECT 1 FROM lifecycle_events WHERE lifecycle_id=%s AND stage='execution' LIMIT 1", [lc_id])
        if cur2.fetchone():
            stats["skipped"] += 1
            continue

        # Execution event
        write_event(conn, lc_id, "execution", "order_filled" if entry else "order_submitted",
                    status="filled" if entry else "submitted",
                    symbol=sym, strategy_id=sid, signal_id=str(sig_id) if sig_id else None,
                    paper_trade_id=tid, source_script="alpaca_paper_adapter.py",
                    source_table="paper_trades", source_pk=str(tid),
                    payload={"entry_price": float(entry) if entry else None, "account": acct},
                    event_ts=etime, dry_run=dry_run)

        # Stop event
        if stop:
            write_event(conn, lc_id, "stop_placement", "initial_stop_set", status="active",
                        symbol=sym, strategy_id=sid, paper_trade_id=tid,
                        payload={"stop_loss": float(stop)},
                        event_ts=etime, dry_run=dry_run)

        # Exit event
        if exit_t:
            write_event(conn, lc_id, "exit", "position_closed", status=exit_r or "closed",
                        symbol=sym, strategy_id=sid, paper_trade_id=tid,
                        payload={"exit_price": float(exit_p) if exit_p else None,
                                 "pnl": float(pnl) if pnl else None,
                                 "exit_reason": exit_r},
                        event_ts=exit_t, dry_run=dry_run)

        stats["trades"] += 1

    # 3. Backfill from paper_execution_quality
    log.info("Backfilling TCA...")
    cur.execute("""SELECT id, symbol, strategy_id, paper_trade_id, proposal_id,
                          fill_quality, slippage_pct, created_at
                   FROM paper_execution_quality ORDER BY id""")
    for row in cur.fetchall():
        eqid, sym, sid, ptid, propid, quality, slip, created = row
        lc_id = generate_lifecycle_id(sym, sid, f"tca-{eqid}")

        cur2 = conn.cursor()
        cur2.execute("SELECT 1 FROM lifecycle_events WHERE lifecycle_id=%s AND stage='tca' LIMIT 1", [lc_id])
        if cur2.fetchone():
            stats["skipped"] += 1
            continue

        write_event(conn, lc_id, "tca", "execution_quality_assessed", status=quality,
                    symbol=sym, strategy_id=sid, paper_trade_id=ptid,
                    proposal_id=str(propid) if propid else None,
                    execution_quality_id=eqid,
                    source_script="paper_execution_quality_analyzer.py",
                    source_table="paper_execution_quality", source_pk=str(eqid),
                    payload={"fill_quality": quality, "slippage_pct": float(slip) if slip else None},
                    event_ts=created, dry_run=dry_run)
        stats["tca"] += 1

    log.info(f"Backfill {'DRY RUN' if dry_run else 'APPLIED'}: "
             f"{stats['proposals']} proposals, {stats['trades']} trades, "
             f"{stats['tca']} TCA, {stats['skipped']} skipped (already exist)")
    return stats


def main():
    p = argparse.ArgumentParser(description="Lifecycle Event Writer — traceability spine")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backfill", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    conn = _get_conn()
    if not conn:
        log.error("No DB connection")
        sys.exit(1)

    if args.backfill:
        stats = backfill(conn, dry_run=args.dry_run)
        log.info(f"Backfill complete: {stats}")
    else:
        log.info("No action specified. Use --backfill --dry-run to preview.")

    conn.close()


if __name__ == "__main__":
    main()
