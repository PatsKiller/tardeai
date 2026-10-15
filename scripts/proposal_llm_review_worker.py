#!/usr/bin/env python3
"""proposal_llm_review_worker.py — Process queued LLM reviews for proposals.

Pulls PENDING rows from proposal_llm_review_queue and runs qwen3:14b review
via the existing proposal_llm_reviewer.py infrastructure. That retired local-model child
remains an owner blocker; the offline CLI preparation neither invokes nor restores it.

Usage:
    .venv/bin/python3 scripts/proposal_llm_review_worker.py --dry-run
    .venv/bin/python3 scripts/proposal_llm_review_worker.py --run --limit 2
    .venv/bin/python3 scripts/proposal_llm_review_worker.py --proposal-id 43 --run
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_ENV_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def _load_env():
    from lib.env_bootstrap import load_env
    load_env(names=_ENV_KEYS)

log = logging.getLogger("llm_review_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def get_db():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def fetch_queue(conn, limit=2, proposal_id=None):
    """Get PENDING queue rows."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if proposal_id:
        cur.execute("SELECT * FROM proposal_llm_review_queue WHERE proposal_id = %s", [proposal_id])
    else:
        cur.execute("""
            SELECT * FROM proposal_llm_review_queue
            WHERE queue_status = 'PENDING'
            ORDER BY priority ASC, queued_at ASC
            LIMIT %s
        """, [limit])
    rows = [dict(r) for r in cur.fetchall()]
    # Release the read txn — the caller waits minutes on the LLM gate + Ollama warmup before
    # touching the DB again, and PG kills idle-in-transaction at 120s (took the whole run down:
    # the first status UPDATE died with "SSL connection has been closed unexpectedly").
    conn.commit()
    return rows


def process_one(conn, queue_row, dry_run=False):
    """Process a single LLM review queue entry."""
    qid = queue_row['id']
    pid = queue_row['proposal_id']
    symbol = queue_row['symbol']

    if dry_run:
        log.info(f"[dry-run] Would review #{pid} {symbol}")
        return {'proposal_id': pid, 'symbol': symbol, 'status': 'dry_run'}

    cur = conn.cursor()

    # Mark as processing
    cur.execute("""
        UPDATE proposal_llm_review_queue
        SET queue_status = 'PROCESSING', started_at = NOW(),
            attempts = COALESCE(attempts, 0) + 1
        WHERE id = %s
    """, [qid])
    conn.commit()

    try:
        from proposal_llm_reviewer import review_proposal
        result = review_proposal(conn, pid)

        if result and result.get('success'):
            cur.execute("""
                UPDATE proposal_llm_review_queue
                SET queue_status = 'COMPLETED', finished_at = NOW()
                WHERE id = %s
            """, [qid])
            cur.execute("""
                UPDATE paper_trade_proposals
                SET llm_review_status = 'COMPLETE'
                WHERE id = %s
            """, [pid])
            conn.commit()
            model_name = result.get('model', 'unknown')
            log.info(f"[review] #{pid} {symbol}: {result.get('narrative_source')} model={model_name} decision={result.get('review', {}).get('decision')}")
            return {'proposal_id': pid, 'symbol': symbol, 'status': 'completed',
                    'source': result.get('narrative_source'), 'model': model_name, 'decision': result.get('review', {}).get('decision')}
        else:
            error = result.get('error', 'unknown') if result else 'no result'
            cur.execute("""
                UPDATE proposal_llm_review_queue
                SET queue_status = 'PENDING', last_error = %s
                WHERE id = %s
            """, [str(error)[:500], qid])
            cur.execute("""
                UPDATE paper_trade_proposals
                SET llm_review_status = 'ERROR'
                WHERE id = %s
            """, [pid])
            conn.commit()
            return {'proposal_id': pid, 'symbol': symbol, 'status': 'error', 'error': error}

    except Exception as e:
        cur.execute("""
            UPDATE proposal_llm_review_queue
            SET queue_status = 'PENDING', last_error = %s
            WHERE id = %s
        """, [str(e)[:500], qid])
        cur.execute("""
            UPDATE paper_trade_proposals
            SET llm_review_status = 'ERROR'
            WHERE id = %s
        """, [pid])
        conn.commit()
        log.warning(f"[review] #{pid} {symbol}: ERROR {e}")
        return {'proposal_id': pid, 'symbol': symbol, 'status': 'error', 'error': str(e)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Proposal LLM review worker", allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true", help="offline plan; overrides --run")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--proposal-id", type=int)
    parser.add_argument("--throttle", type=int, default=10,
                        help="Seconds to wait between reviews (default 10)")
    args = parser.parse_args(argv)
    if not (args.run or args.dry_run):
        parser.error("one of --dry-run or --run is required")
    if args.dry_run:
        print(f"DRY-RUN proposal-llm-review-worker: would review pending proposals; limit={args.limit} proposal_id={args.proposal_id}; no queue claims, DB, model, network or writes")
        return 0
    from pipeline_registry import PipelineRun
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    conn = None
    try:
        _load_env()
        conn = get_db()
        with PipelineRun('proposal_llm_review_worker', triggered_by='cli') as pipe:
            queue = fetch_queue(conn, limit=args.limit, proposal_id=args.proposal_id)
            log.info(f"Found {len(queue)} queued LLM reviews")

            # Warmup Ollama before processing (handles cold GPU model load)
            # Never on the governed-bridge path (n8n): the warmup is a local model call.
            if queue and args.run and os.environ.get("TRADEAI_LLM_VIA_BRIDGE", "off").strip().lower() not in {
                    "1", "on", "bridge"}:
                try:
                    from local_llm import warmup_ollama
                    log.info("Warming up Ollama (may take minutes on cold start)...")
                    if warmup_ollama():
                        log.info("Ollama warm — starting reviews")
                    else:
                        log.warning("Ollama warmup failed — will attempt reviews with fallback chain")
                except ImportError:
                    pass

            results = []
            for i, q in enumerate(queue):
                r = process_one(conn, q, dry_run=args.dry_run)
                results.append(r)
                # Throttle between jobs to avoid GPU contention
                if i < len(queue) - 1 and args.run:
                    import time
                    log.info(f"Throttle: waiting {args.throttle}s before next review...")
                    time.sleep(args.throttle)

            pipe.rows(len(results))

        prefix = "[DRY RUN] " if args.dry_run else ""
        print(f"\n{prefix}LLM Review Worker")
        print(f"{prefix}{'=' * 40}")
        print(f"  Queue size: {len(queue)}")
        completed = sum(1 for r in results if r.get('status') == 'completed')
        errors = sum(1 for r in results if r.get('status') == 'error')
        print(f"  Completed: {completed}")
        print(f"  Errors: {errors}")
        for r in results:
            print(f"  #{r['proposal_id']} {r['symbol']}: {r['status']}")
        code = 1 if errors else 0
        write_lane_receipt("proposal-llm-review-worker", ok=code == 0, exit_code=code,
                           started_at=started, summary={"queued": len(queue), "completed": completed,
                                                      "failed": errors})
        return code
    except Exception as exc:
        write_lane_receipt("proposal-llm-review-worker", ok=False, exit_code=1,
                           started_at=started, error=type(exc).__name__)
        raise
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
