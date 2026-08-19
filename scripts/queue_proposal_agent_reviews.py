#!/usr/bin/env python3
"""queue_proposal_agent_reviews.py — Queue agent review jobs for GO signals and pending proposals.

Inserts rows into proposal_agent_reviews (pending) and queues watchlist_agent_jobs
so that process_watchlist_agent_jobs.py can execute Maria/Risk/Steph reviews.

Also ensures symbols appear in watchlist_items so the agent framework can find them.

Usage:
    .venv/bin/python scripts/queue_proposal_agent_reviews.py --dry-run
    .venv/bin/python scripts/queue_proposal_agent_reviews.py --apply
    .venv/bin/python scripts/queue_proposal_agent_reviews.py --symbol EVC --apply
"""
import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("queue_proposal_agent_reviews")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

AGENTS = ["maria", "risk_agent", "steph"]


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def get_target_symbols(conn, symbol=None):
    """Get current-day GO symbols and pending proposal symbols (deduplicated)."""
    cur = conn.cursor()
    if symbol:
        return [{"symbol": symbol, "source": "manual"}]

    cur.execute("""
        SELECT symbol,
               CASE WHEN has_proposal THEN 'paper_proposal' ELSE 'go_signal' END as source
        FROM (
            SELECT symbol,
                   EXISTS(SELECT 1 FROM paper_trade_proposals ptp WHERE ptp.symbol=u.symbol AND ptp.status IN ('PENDING','APPROVED_FOR_PAPER_TEST')) as has_proposal
            FROM (
                SELECT DISTINCT symbol FROM trade_ai_scans
                WHERE DATE(scanned_at) = CURRENT_DATE AND decision = 'GO'
                UNION
                SELECT DISTINCT symbol FROM paper_trade_proposals
                -- APPROVED_FOR_PAPER_TEST rows still need reviews (their promote gate demands
                -- them) but the PENDING-only filter meant the ATM lane never got any queued
                WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST')
            ) u
        ) v
        ORDER BY symbol
    """)
    return [{"symbol": r[0], "source": r[1]} for r in cur.fetchall()]


def get_pending_proposals_for_symbol(conn, symbol):
    """Get pending proposal IDs for a symbol."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, strategy_id FROM paper_trade_proposals
        WHERE symbol = %s AND status IN ('PENDING','APPROVED_FOR_PAPER_TEST')
        ORDER BY created_at DESC
    """, [symbol])
    return [{"id": r[0], "strategy_id": r[1]} for r in cur.fetchall()]


def check_existing_review(conn, proposal_id, agent_name):
    """Check if review already exists for this proposal+agent."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM proposal_agent_reviews
        WHERE proposal_id = %s AND agent_name = %s
    """, [proposal_id, agent_name])
    return cur.fetchone() is not None


def check_existing_job(conn, symbol, agent_name, proposal_id=None):
    """Check if a queued/running job exists for this symbol+agent (scoped to the proposal when known).
    The old symbol-level same-day dedup let an UNRELATED job (another proposal, go-signal research)
    suppress a proposal's review with no retry — #1348 permanently lost maria that way."""
    cur = conn.cursor()
    if proposal_id is not None:
        cur.execute("""
            SELECT id FROM watchlist_agent_jobs
            WHERE symbol = %s AND requested_agent = %s
            AND status IN ('queued', 'running')
            AND payload->>'proposal_id' = %s
            LIMIT 1
        """, [symbol, agent_name, str(proposal_id)])
    else:
        cur.execute("""
            SELECT id FROM watchlist_agent_jobs
            WHERE symbol = %s AND requested_agent = %s
            AND status IN ('queued', 'running')
            AND created_at::date = CURRENT_DATE
            LIMIT 1
        """, [symbol, agent_name])
    return cur.fetchone() is not None


def ensure_watchlist_item(conn, symbol, source, dry_run=False):
    """Ensure symbol exists in watchlist_items for agent framework."""
    cur = conn.cursor()
    wl_source = 'trade_ai_go' if source == 'go_signal' else 'paper_proposal'
    cur.execute("""
        SELECT id FROM watchlist_items
        WHERE symbol = %s AND source = %s
    """, [symbol, wl_source])
    if cur.fetchone():
        cur.execute("""
            UPDATE watchlist_items SET last_seen_at = NOW(), updated_at = NOW(), status = 'active'
            WHERE symbol = %s AND source = %s
        """, [symbol, wl_source])
        return "updated"
    if not dry_run:
        cur.execute("""
            INSERT INTO watchlist_items (symbol, source, bucket, status, score)
            VALUES (%s, %s, 'proposal_review', 'active', 50)
            ON CONFLICT (symbol, source, COALESCE(bucket, '__none__')) DO UPDATE
            SET last_seen_at = NOW(), updated_at = NOW(), status = 'active'
        """, [symbol, wl_source])
        return "created"
    return "would_create"


def queue_agent_job(conn, symbol, agent_name, proposal_id, strategy_id, dry_run=False):
    """Queue a watchlist_agent_job for the symbol+agent."""
    job_id = str(uuid.uuid4())[:12]
    note = f"Proposal #{proposal_id} ({strategy_id}) agent review"

    if dry_run:
        log.info(f"  [dry-run] Would queue {agent_name} for {symbol} (proposal #{proposal_id})")
        return {"queued": False, "dry_run": True}

    cur = conn.cursor()
    sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
    from agent_job_enqueue_governance import EnqueueRequest, governed_enqueue
    res = governed_enqueue(cur, EnqueueRequest(
        symbol=symbol,
        requested_agent=agent_name,
        request_type="proposal_review",
        submitted_from="proposal_agent_queue",
        priority=3,
        note=note,
        job_id=job_id,
        payload={"proposal_id": proposal_id, "strategy_id": strategy_id},
        universe_tier="T1",
        material=True,
    ))
    if res.action != "INSERT":
        return {"queued": False, "job_id": res.job_id, "action": res.action}

    return {"queued": True, "job_id": job_id}


def create_pending_review(conn, proposal_id, symbol, strategy_id, agent_name, dry_run=False):
    """Create a pending proposal_agent_reviews row."""
    if dry_run:
        return {"created": False, "dry_run": True}

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO proposal_agent_reviews (proposal_id, symbol, strategy_id, agent_name, role, status)
        VALUES (%s, %s, %s, %s, %s, 'pending')
        ON CONFLICT (proposal_id, agent_name) DO NOTHING
    """, [proposal_id, symbol, strategy_id, agent_name, agent_name])
    return {"created": True}


def run(symbol=None, dry_run=True):
    conn = get_conn()
    try:
        targets = get_target_symbols(conn, symbol)
        log.info(f"Found {len(targets)} target symbols")

        stats = {"symbols": 0, "jobs_queued": 0, "reviews_created": 0, "skipped_existing": 0, "details": []}

        for t in targets:
            sym = t["symbol"]
            source = t["source"]
            stats["symbols"] += 1

            # Ensure watchlist item exists
            wl_result = ensure_watchlist_item(conn, sym, source, dry_run)

            # Get pending proposals for this symbol
            proposals = get_pending_proposals_for_symbol(conn, sym)
            if not proposals:
                # Symbol has GO signal but no proposal yet — queue for watchlist agent framework
                for agent in AGENTS:
                    if check_existing_job(conn, sym, agent):
                        stats["skipped_existing"] += 1
                        continue
                    # Queue a job without proposal_id
                    if not dry_run:
                        job_id = str(uuid.uuid4())[:12]
                        cur = conn.cursor()
                        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
                        from agent_job_enqueue_governance import EnqueueRequest, governed_enqueue
                        res = governed_enqueue(cur, EnqueueRequest(
                            symbol=sym,
                            requested_agent=agent,
                            request_type="go_signal_review",
                            submitted_from="proposal_agent_queue",
                            priority=3,
                            note=f"GO signal review for {sym}",
                            job_id=job_id,
                            universe_tier="T1",
                            material=True,
                        ))
                        if res.action == "INSERT":
                            stats["jobs_queued"] += 1
                        else:
                            stats["skipped_existing"] += 1
                    else:
                        log.info(f"  [dry-run] Would queue {agent} for {sym} (GO signal, no proposal)")
                        stats["jobs_queued"] += 1
                if not dry_run:
                    conn.commit()
                continue

            for prop in proposals:
                pid = prop["id"]
                sid = prop["strategy_id"]

                for agent in AGENTS:
                    # Skip if review already exists
                    if check_existing_review(conn, pid, agent):
                        stats["skipped_existing"] += 1
                        log.info(f"  {sym}: {agent} review for #{pid} already exists, skipping")
                        continue

                    # Skip if a job for THIS proposal+agent is already queued/running
                    if check_existing_job(conn, sym, agent, proposal_id=pid):
                        stats["skipped_existing"] += 1
                        continue

                    # Create pending review placeholder
                    create_pending_review(conn, pid, sym, sid, agent, dry_run)
                    stats["reviews_created"] += 1

                    # Queue agent job
                    result = queue_agent_job(conn, sym, agent, pid, sid, dry_run)
                    if result.get("queued"):
                        stats["jobs_queued"] += 1

                stats["details"].append({"symbol": sym, "proposal_id": pid, "strategy_id": sid})

            if not dry_run:
                conn.commit()

        log.info(f"\nQueue summary: symbols={stats['symbols']} "
                 f"jobs_queued={stats['jobs_queued']} reviews_created={stats['reviews_created']} "
                 f"skipped={stats['skipped_existing']}")
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Queue agent reviews for proposals and GO signals")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--apply", action="store_true", help="Actually queue jobs")
    parser.add_argument("--symbol", type=str, help="Single symbol to queue")
    parser.add_argument("--proposal-id", type=int, default=None, help="Queue reviews for specific proposal ID")
    args = parser.parse_args()

    # If --proposal-id given, look up the symbol
    symbol = args.symbol
    if args.proposal_id and not symbol:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT symbol FROM paper_trade_proposals WHERE id=%s", [args.proposal_id])
            row = cur.fetchone()
            if row:
                symbol = row[0]
                log.info(f"Proposal #{args.proposal_id} → symbol {symbol}")
            else:
                print(f"Proposal {args.proposal_id} not found")
                sys.exit(1)
        finally:
            conn.close()

    dry = not args.apply
    result = run(symbol=symbol, dry_run=dry)
    print(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=2))
