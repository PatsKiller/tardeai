#!/usr/bin/env python3
"""backfill_lifecycle_trace_v3_1.py — Backfill prospect→signal→proposal traceability.

Usage:
    python scripts/backfill_lifecycle_trace_v3_1.py --dry-run
    python scripts/backfill_lifecycle_trace_v3_1.py --apply
"""
import argparse, json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [trace-backfill] %(message)s")
log = logging.getLogger("trace_backfill")

from lifecycle_trace import (
    find_or_create_trace, append_trace_event, detect_duplicate_proposals,
    normalize_symbol, normalize_strategy,
)


def _get_conn():
    from db_adapter import _get_conn as gc
    return gc()


def backfill(conn, dry_run=True):
    cur = conn.cursor()
    stats = {"signals": 0, "proposals": 0, "trades": 0, "traces_created": 0,
             "traces_updated": 0, "events": 0, "dedup_groups": 0, "missing_metadata": 0}

    # 1. Backfill from strategy_signals
    log.info("Backfilling signals...")
    cur.execute("""SELECT id, symbol, strategy_id, signal_score, signal_grade, status, fired_at
                   FROM strategy_signals ORDER BY id""")
    for row in cur.fetchall():
        sid, sym, strat, score, grade, decision, fired = row
        if not sym:
            stats["missing_metadata"] += 1
            continue
        tid, created = find_or_create_trace(
            conn, sym, strat, "signal", source_system="orchestrator",
            source_id=f"signal-{sid}", signal_id=str(sid),
            score=float(score) if score else None,
            reason=f"grade={grade} decision={decision}",
            dry_run=dry_run)
        if created:
            stats["traces_created"] += 1
        else:
            stats["traces_updated"] += 1
        stats["signals"] += 1
        append_trace_event(conn, tid, "signal", "signal_scored",
                           source_script="trade_ai_orchestrator.py",
                           source_table="strategy_signals", source_id=str(sid),
                           status=decision, message=f"Score={score} Grade={grade}",
                           dry_run=dry_run)
        stats["events"] += 1

    # 2. Backfill from paper_trade_proposals
    log.info("Backfilling proposals...")
    cur.execute("""SELECT id, symbol, strategy_id, source_signal_id, signal_score,
                          signal_decision, created_at
                   FROM paper_trade_proposals ORDER BY id""")
    for row in cur.fetchall():
        pid, sym, strat, sig_id, score, decision, created = row
        if not sym:
            stats["missing_metadata"] += 1
            continue
        tid, created_new = find_or_create_trace(
            conn, sym, strat, "proposal", source_system="proposal_generator",
            source_id=f"proposal-{pid}", signal_id=str(sig_id) if sig_id else None,
            proposal_id=str(pid), score=float(score) if score else None,
            dry_run=dry_run)
        if created_new:
            stats["traces_created"] += 1
        else:
            stats["traces_updated"] += 1
        stats["proposals"] += 1
        append_trace_event(conn, tid, "proposal", "proposal_created",
                           source_script="auto_proposal_generator.py",
                           source_table="paper_trade_proposals", source_id=str(pid),
                           status=decision or "pending",
                           dry_run=dry_run)
        stats["events"] += 1

    # 3. Backfill from paper_trades (link to traces)
    log.info("Backfilling trades...")
    cur.execute("""SELECT id, symbol, strategy_id, signal_id, entry_price, entry_time
                   FROM paper_trades WHERE entry_price IS NOT NULL ORDER BY id""")
    for row in cur.fetchall():
        tid_db, sym, strat, sig_id, entry, etime = row
        if not sym:
            continue
        tid, created_new = find_or_create_trace(
            conn, sym, strat, "execution", source_system="paper_submitter",
            source_id=f"trade-{tid_db}", signal_id=str(sig_id) if sig_id else None,
            paper_trade_id=tid_db,
            dry_run=dry_run)
        if created_new:
            stats["traces_created"] += 1
        else:
            stats["traces_updated"] += 1
        stats["trades"] += 1
        append_trace_event(conn, tid, "execution", "trade_filled",
                           source_table="paper_trades", source_id=str(tid_db),
                           status="filled",
                           dry_run=dry_run)
        stats["events"] += 1

    # 4. Detect duplicate proposals
    log.info("Detecting duplicate proposals...")
    dedup_groups = detect_duplicate_proposals(conn, dry_run=dry_run)
    stats["dedup_groups"] = len(dedup_groups)

    log.info(f"{'DRY RUN' if dry_run else 'APPLIED'}: {stats}")
    return stats, dedup_groups


def main():
    p = argparse.ArgumentParser(description="Backfill lifecycle trace v3.1")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--json-out", type=str)
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    conn = _get_conn()
    if not conn:
        log.error("No DB connection")
        sys.exit(1)

    stats, dedup_groups = backfill(conn, dry_run=args.dry_run)

    result = {
        "mode": "dry_run" if args.dry_run else "applied",
        "stats": stats,
        "dedup_groups": len(dedup_groups),
        "dedup_summary": [{"key": g["duplicate_key"], "count": g["duplicate_count"]}
                          for g in dedup_groups[:20]],
        "safety": {
            "proposals_modified": "NONE",
            "paper_trades_modified": "NONE",
            "orders_placed": "NONE",
        },
    }

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(result, indent=2, default=str))

    print(json.dumps(result, indent=2, default=str))
    conn.close()


if __name__ == "__main__":
    main()
