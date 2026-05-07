#!/usr/bin/env python3
"""proposal_enrichment_loop.py — Continuous enrichment for pending proposals.

Runs every 5 minutes during market hours. Finds proposals with missing
agent reviews, LLM analysis, or quality reviews and runs them.

Usage:
    .venv/bin/python scripts/proposal_enrichment_loop.py          # single pass
    .venv/bin/python scripts/proposal_enrichment_loop.py --loop   # continuous 5-min loop
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("proposal_enrichment_loop")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(message)s")

BASE = str(PROJECT_ROOT)
PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")


def get_db():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def find_unenriched_proposals(conn) -> list:
    """Find PENDING proposals missing agent reviews, LLM analysis, or quality review."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""
        SELECT p.id, p.symbol, p.strategy_id, p.created_at,
               p.signal_grade, p.signal_score,
               (SELECT COUNT(DISTINCT agent_name)
                FROM proposal_agent_reviews par
                WHERE par.proposal_id = p.id
                AND par.status != 'pending'
               ) as agent_review_count,
               (SELECT COUNT(*) FROM paper_proposal_analysis a
                WHERE a.proposal_id = p.id
               ) as llm_analysis_count,
               (SELECT COUNT(*) FROM proposal_quality_reviews q
                WHERE q.proposal_id = p.id
               ) as quality_review_count
        FROM paper_trade_proposals p
        WHERE p.status = 'PENDING'
        AND p.expires_at > NOW()
        ORDER BY p.signal_score DESC NULLS LAST, p.created_at ASC
    """)
    return [dict(r) for r in cur.fetchall()]


def enrich_proposal(proposal: dict) -> dict:
    """Run missing enrichment for a single proposal. Returns status dict."""
    pid = proposal["id"]
    symbol = proposal["symbol"]
    status = {"proposal_id": pid, "symbol": symbol, "actions": []}

    # Queue agent reviews if missing (need at least 1 completed)
    if proposal["agent_review_count"] < 1:
        log.info(f"#{pid} {symbol}: queuing agent reviews")
        try:
            r = subprocess.run(
                [PYTHON, f"{BASE}/scripts/queue_proposal_agent_reviews.py",
                 "--proposal-id", str(pid), "--apply"],
                capture_output=True, text=True, timeout=60, cwd=BASE
            )
            status["actions"].append(
                f"agent_reviews: {'queued' if r.returncode == 0 else 'failed'}"
            )
        except Exception as e:
            status["actions"].append(f"agent_reviews: error ({e})")

    # Run LLM analysis if missing
    if proposal["llm_analysis_count"] < 1:
        log.info(f"#{pid} {symbol}: running LLM analysis")
        try:
            r = subprocess.run(
                [PYTHON, f"{BASE}/scripts/proposal_intelligence_analyzer.py",
                 "--proposal-id", str(pid), "--apply"],
                capture_output=True, text=True, timeout=180, cwd=BASE
            )
            status["actions"].append(
                f"llm_analysis: {'done' if r.returncode == 0 else 'failed'}"
            )
        except subprocess.TimeoutExpired:
            status["actions"].append("llm_analysis: timeout")
        except Exception as e:
            status["actions"].append(f"llm_analysis: error ({e})")

    # Run quality review if missing
    if proposal["quality_review_count"] < 1:
        log.info(f"#{pid} {symbol}: running quality review")
        try:
            r = subprocess.run(
                [PYTHON, f"{BASE}/scripts/proposal_quality_reviewer.py",
                 "--proposal-id", str(pid), "--apply"],
                capture_output=True, text=True, timeout=60, cwd=BASE
            )
            status["actions"].append(
                f"quality_review: {'done' if r.returncode == 0 else 'failed'}"
            )
        except Exception as e:
            status["actions"].append(f"quality_review: error ({e})")

    return status


def run_once():
    """Single enrichment pass over all pending proposals."""
    conn = get_db()
    try:
        proposals = find_unenriched_proposals(conn)
        needs_enrichment = [
            p for p in proposals
            if p["agent_review_count"] < 1
            or p["llm_analysis_count"] < 1
            or p["quality_review_count"] < 1
        ]

        log.info(
            f"Found {len(proposals)} pending proposals, "
            f"{len(needs_enrichment)} need enrichment"
        )

        results = []
        for proposal in needs_enrichment:
            result = enrich_proposal(proposal)
            results.append(result)
            log.info(
                f"#{proposal['id']} {proposal['symbol']}: "
                f"{', '.join(result['actions']) or 'nothing needed'}"
            )

        return results
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Proposal enrichment loop")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously every 5 minutes")
    parser.add_argument("--interval", type=int, default=300,
                        help="Loop interval in seconds (default: 300)")
    args = parser.parse_args()

    if args.loop:
        log.info(f"Starting enrichment loop (interval: {args.interval}s)")
        while True:
            try:
                results = run_once()
                enriched = sum(1 for r in results if r["actions"])
                log.info(f"Loop pass complete: {enriched} proposals enriched")
            except Exception as e:
                log.error(f"Enrichment loop error: {e}")
            time.sleep(args.interval)
    else:
        results = run_once()
        enriched = sum(1 for r in results if r["actions"])
        print(f"Enrichment pass complete: {enriched} proposals enriched")
        for r in results:
            print(f"  #{r['proposal_id']} {r['symbol']}: "
                  f"{', '.join(r['actions']) or 'fully enriched'}")


if __name__ == "__main__":
    main()
