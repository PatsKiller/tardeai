#!/usr/bin/env python3
"""data_gap_resolver.py — closes data gaps before overnight runs.

For each open gap in data_gap_registry, dispatch the appropriate
enrichment or agent job. Updates status to 'enriching' then 'resolved'.

Usage:
    .venv/bin/python scripts/data_gap_resolver.py
    .venv/bin/python scripts/data_gap_resolver.py --pre-overnight
    .venv/bin/python scripts/data_gap_resolver.py --weekly-audit
    .venv/bin/python scripts/data_gap_resolver.py --dry-run

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def get_db_connection():
    import psycopg2
    env_path = PROJ / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} [gap-resolver] {msg}", flush=True)


# ── Resolution actions ───────────────────────────────────────────────

def _resolve_missing_div_yield(symbol, conn):
    """Force re-snapshot of ticker to pick up dividend yield."""
    cur = conn.cursor()
    # Check if we already have div_yield somewhere
    cur.execute("""
        SELECT data->>'div_yield' FROM ticker_snapshot_daily
        WHERE symbol = %s ORDER BY snapshot_date DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row and row[0] and row[0] not in ('', 'None', 'null'):
        return True  # Already resolved
    # Queue enrichment agent job
    try:
        # Check if already queued
        cur.execute("""
            SELECT id FROM watchlist_agent_jobs
            WHERE symbol = %s AND requested_agent = 'maria_research'
              AND submitted_from = 'gap_resolver' AND status = 'queued'
        """, [symbol])
        if cur.fetchone():
            return True  # Already dispatched
        import hashlib
        job_id = f"gap_{symbol.lower()}_maria_{hashlib.md5(f'{symbol}:enrich:{datetime.now().date()}'.encode()).hexdigest()[:6]}"
        cur.execute("""
            INSERT INTO watchlist_agent_jobs
                (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, created_at)
            VALUES (%s, %s, 'maria_research', 'enrichment', 'data_gap: missing div_yield', 'queued', 1, 'gap_resolver', NOW())
        """, [job_id, symbol])
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        return False


def _resolve_missing_sector(symbol, conn):
    """Similar to div_yield — queue enrichment."""
    return _resolve_missing_div_yield(symbol, conn)


def _resolve_missing_market_data(symbol, conn):
    """Queue enrichment for missing market data fields."""
    return _resolve_missing_div_yield(symbol, conn)


def _resolve_missing_catalyst(symbol, conn):
    """Dispatch Maria research agent to find catalysts."""
    cur = conn.cursor()
    try:
        cur = conn.cursor()
        # Check if already queued
        cur.execute("""
            SELECT id FROM watchlist_agent_jobs
            WHERE symbol = %s AND requested_agent = 'maria_research'
              AND submitted_from = 'gap_resolver' AND status = 'queued'
        """, [symbol])
        if cur.fetchone():
            return True  # Already queued
        import hashlib
        job_id = f"gap_{symbol.lower()}_catalyst_{hashlib.md5(f'{symbol}:catalyst:{datetime.now().date()}'.encode()).hexdigest()[:6]}"
        cur.execute("""
            INSERT INTO watchlist_agent_jobs
                (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, created_at)
            VALUES (%s, %s, 'maria_research', 'catalyst_research', 'data_gap: missing catalyst for recovery watch', 'queued', 1, 'gap_resolver', NOW())
        """, [job_id, symbol])
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        return False


def _resolve_missing_thesis(symbol, conn):
    """Recover original buy thesis from proposals or trade journal."""
    cur = conn.cursor()
    # Try paper_trade_proposals
    cur.execute("""
        SELECT setup_description, catalyst, strategy_prompt_context
        FROM paper_trade_proposals
        WHERE symbol = %s AND setup_description IS NOT NULL
        ORDER BY created_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row and any(row):
        thesis = row[0] or row[2] or row[1] or ''
        if thesis:
            # Store recovered thesis in ticker_strategy_classifications notes
            cur.execute("""
                UPDATE ticker_strategy_classifications
                SET notes = COALESCE(notes, '') || E'\nRecovered thesis: ' || %s
                WHERE symbol = %s AND active = true
            """, [thesis[:500], symbol])
            conn.commit()
            return True
    return False


def _resolve_stale_news(symbol, conn):
    """Queue Maria for fresh news research."""
    return _resolve_missing_catalyst(symbol, conn)


def _resolve_missing_setup(symbol, conn):
    """Reconstruct setup from paper_trades + proposals."""
    cur = conn.cursor()
    cur.execute("""
        SELECT pt.id, pp.setup_description, pp.catalyst,
               pp.proposed_entry, pp.proposed_stop
        FROM paper_trades pt
        LEFT JOIN paper_trade_proposals pp ON pp.paper_trade_id = pt.id
        WHERE pt.symbol = %s
        ORDER BY pt.created_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row and any(row[1:]):
        return True  # Data exists, gap may have been about format not absence
    return False


GAP_RESOLVERS = {
    'missing_div_yield': _resolve_missing_div_yield,
    'missing_sector': _resolve_missing_sector,
    'missing_market_data': _resolve_missing_market_data,
    'missing_catalyst': _resolve_missing_catalyst,
    'missing_thesis': _resolve_missing_thesis,
    'stale_news': _resolve_stale_news,
    'missing_setup_details': _resolve_missing_setup,
}


def _requeue_source_job(gap_id, conn):
    """Re-queue the original job that flagged this gap with elevated priority."""
    cur = conn.cursor()
    cur.execute("""
        SELECT q.job_type, q.symbol, q.reason_codes, q.source_table, q.source_id
        FROM data_gap_registry g
        JOIN deep_overnight_llm_queue q ON q.id = g.source_job_id
        WHERE g.id = %s
    """, [gap_id])
    row = cur.fetchone()
    if not row:
        return False
    job_type, symbol, reasons, src_table, src_id = row
    import hashlib
    new_hash = hashlib.md5(f"{job_type}:{symbol}:gap_resolved:{gap_id}".encode()).hexdigest()
    cur.execute("""
        INSERT INTO deep_overnight_llm_queue
            (job_type, symbol, priority_tier, priority_score,
             reason_codes, input_hash, source_table, source_id,
             source_script, status)
        VALUES (%s, %s, 'P1', 80, %s, %s, %s, %s, 'gap_resolver', 'pending')
        ON CONFLICT DO NOTHING
    """, [job_type, symbol, ['gap_resolved', f'gap_id:{gap_id}'],
          new_hash, src_table, src_id])
    conn.commit()
    return cur.rowcount > 0


def resolve_gaps(dry_run=False, pre_overnight=False, weekly_audit=False):
    """Main gap resolution loop."""
    conn = get_db_connection()
    cur = conn.cursor()

    # Get open gaps, high severity first
    limit = 100 if pre_overnight else 50
    cur.execute("""
        SELECT id, symbol, gap_type, gap_detail, source_job_id
        FROM data_gap_registry
        WHERE status = 'open'
        ORDER BY
          CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
          detected_at ASC
        LIMIT %s
    """, [limit])
    gaps = cur.fetchall()
    log(f"Found {len(gaps)} open gaps" + (" (pre-overnight sweep)" if pre_overnight else ""))

    if not gaps:
        conn.close()
        return

    resolved, failed, skipped = 0, 0, 0
    for gap_id, symbol, gap_type, detail, source_job_id in gaps:
        if not symbol:
            skipped += 1
            continue

        resolver = GAP_RESOLVERS.get(gap_type)
        if not resolver:
            # For 'explicit' type gaps, try catalyst resolver as fallback
            if gap_type == 'explicit':
                resolver = _resolve_missing_catalyst
            else:
                log(f"  SKIP {symbol}: no resolver for {gap_type}")
                skipped += 1
                continue

        if dry_run:
            log(f"  [DRY] {symbol}: {gap_type} -> would resolve")
            resolved += 1
            continue

        # Mark enriching
        cur.execute("UPDATE data_gap_registry SET status = 'enriching' WHERE id = %s", [gap_id])
        conn.commit()

        try:
            success = resolver(symbol, conn)
            if success:
                cur.execute("""
                    UPDATE data_gap_registry
                    SET status = 'resolved', resolved_at = NOW(), resolved_by = 'gap_resolver_v1'
                    WHERE id = %s
                """, [gap_id])
                conn.commit()
                # Re-queue source job with enriched data
                if source_job_id:
                    _requeue_source_job(gap_id, conn)
                resolved += 1
                log(f"  OK {symbol}: {gap_type}")
            else:
                conn.rollback()
                cur.execute("UPDATE data_gap_registry SET status = 'open' WHERE id = %s", [gap_id])
                conn.commit()
                failed += 1
                log(f"  FAIL {symbol}: {gap_type}")
        except Exception as e:
            conn.rollback()
            cur.execute("UPDATE data_gap_registry SET status = 'open' WHERE id = %s", [gap_id])
            conn.commit()
            failed += 1
            import traceback
            log(f"  ERROR {symbol}: {gap_type} — {e}")
            traceback.print_exc()

    if weekly_audit:
        # Report persistent gaps (open > 7 days)
        cur.execute("""
            SELECT symbol, gap_type, detected_at
            FROM data_gap_registry
            WHERE status = 'open' AND detected_at < NOW() - INTERVAL '7 days'
            ORDER BY detected_at ASC
        """)
        persistent = cur.fetchall()
        if persistent:
            log(f"Persistent gaps (>7 days): {len(persistent)}")
            for sym, gt, det in persistent[:10]:
                log(f"  {sym}: {gt} (since {det})")
            # Mark as abandoned if > 30 days
            cur.execute("""
                UPDATE data_gap_registry SET status = 'abandoned'
                WHERE status = 'open' AND detected_at < NOW() - INTERVAL '30 days'
            """)
            abandoned = cur.rowcount
            if abandoned:
                log(f"Abandoned {abandoned} gaps older than 30 days")
            conn.commit()

    log(f"Done: {resolved} resolved, {failed} failed, {skipped} skipped")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Resolve data gaps before overnight runs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pre-overnight", action="store_true", help="Pre-overnight sweep (higher limit)")
    parser.add_argument("--weekly-audit", action="store_true", help="Report persistent gaps")
    args = parser.parse_args()

    resolve_gaps(dry_run=args.dry_run, pre_overnight=args.pre_overnight,
                 weekly_audit=args.weekly_audit)


if __name__ == "__main__":
    main()
