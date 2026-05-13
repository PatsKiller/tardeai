#!/usr/bin/env python3
"""Build the deep overnight LLM queue with prioritized jobs.

Scans source tables (strategy classifications, closed trades, journal reviews,
proposals, recovery watch) and queues items for gemma3-overnight deep review.

Usage:
    .venv/bin/python scripts/build_deep_overnight_llm_queue.py --dry-run --limit 100
    .venv/bin/python scripts/build_deep_overnight_llm_queue.py --apply --limit 100
    .venv/bin/python scripts/build_deep_overnight_llm_queue.py --apply --job-types strategy_classification,closed_trade_review

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
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


def make_hash(*parts):
    """Create a stable hash from input parts for dedup."""
    raw = "|".join(str(p) for p in parts if p is not None)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_held_symbols():
    """Get currently held portfolio symbols from holdings.json."""
    try:
        path = PROJ / "data" / "portfolios" / "state" / "holdings.json"
        data = json.load(open(path))
        return {h["symbol"] for h in data.get("holdings", []) if h.get("symbol")}
    except Exception:
        return set()


# ─── Job Type Builders ───────────────────────────────────────────────────

def build_strategy_classification_jobs(cur, held_symbols):
    """Queue stale/never-reviewed strategy classifications for gemma deep review."""
    jobs = []

    # Get existing pending/done items to avoid dupes
    cur.execute("""
        SELECT symbol, input_hash FROM deep_overnight_llm_queue
        WHERE job_type = 'strategy_classification' AND status IN ('pending', 'running')
    """)
    existing = {row[0]: row[1] for row in cur.fetchall()}

    # Get last gemma review times from results
    cur.execute("""
        SELECT symbol, MAX(created_at) as last_review
        FROM deep_overnight_llm_results
        WHERE job_type = 'strategy_classification'
        GROUP BY symbol
    """)
    last_reviewed = {row[0]: row[1] for row in cur.fetchall()}

    # Get all active classifications
    cur.execute("""
        SELECT symbol, strategy_type, classification_source, confidence,
               updated_at, rationale
        FROM ticker_strategy_classifications
        WHERE active = true
        ORDER BY symbol
    """)
    rows = cur.fetchall()

    now = datetime.now(timezone.utc)
    for symbol, strategy_type, source, confidence, updated_at, rationale in rows:
        input_hash = make_hash(symbol, strategy_type, source, str(confidence), str(updated_at))

        # Skip if already pending with same hash
        if symbol in existing and existing[symbol] == input_hash:
            continue

        # Calculate priority
        score = 0
        reasons = []
        tier = "P4"

        is_held = symbol in held_symbols
        if is_held:
            score += 100
            reasons.append("held_position")
            tier = "P0"

        last_rev = last_reviewed.get(symbol)
        if last_rev is None:
            score += 30
            reasons.append("never_reviewed")
            if tier == "P4":
                tier = "P3"
        elif last_rev:
            days_stale = (now - last_rev).days if hasattr(last_rev, 'days') else (now - last_rev).total_seconds() / 86400
            if days_stale > 14:
                score += 20
                reasons.append(f"stale_{int(days_stale)}d")
                if tier == "P4":
                    tier = "P3"
            elif days_stale > 7:
                score += 10
                reasons.append(f"aging_{int(days_stale)}d")

        if confidence and float(confidence) < 0.7:
            score += 15
            reasons.append("low_confidence")
            if tier in ("P3", "P4"):
                tier = "P2"

        if source == "llm" and not is_held:
            score += 5
            reasons.append("llm_sourced")

        # Age boost: +1 per day waiting if already in queue
        if symbol in existing:
            score += 1

        jobs.append({
            "job_type": "strategy_classification",
            "symbol": symbol,
            "priority_tier": tier,
            "priority_score": score,
            "reason_codes": reasons,
            "source_script": "build_deep_overnight_llm_queue.py",
            "source_table": "ticker_strategy_classifications",
            "input_hash": input_hash,
            "last_qwen_summary": rationale[:500] if rationale else None,
            "last_qwen_confidence": float(confidence) if confidence else None,
        })

    return jobs


def build_closed_trade_review_jobs(cur, held_symbols):
    """Queue closed trades that need gemma deep review."""
    jobs = []

    cur.execute("""
        SELECT symbol, input_hash FROM deep_overnight_llm_queue
        WHERE job_type = 'closed_trade_review' AND status IN ('pending', 'running')
    """)
    existing = {(row[0],): row[1] for row in cur.fetchall()}

    cur.execute("""
        SELECT id, symbol, account, close_date, pnl, pnl_pct, hold_days,
               r_multiple, stop_used, setup, note, created_at
        FROM trade_closed
        ORDER BY close_date DESC
    """)
    rows = cur.fetchall()

    # Get trades already reviewed by gemma
    cur.execute("""
        SELECT trade_id FROM deep_overnight_llm_results
        WHERE job_type = 'closed_trade_review' AND trade_id IS NOT NULL
    """)
    reviewed_trades = {row[0] for row in cur.fetchall()}

    now = datetime.now(timezone.utc)
    for trade_id, symbol, account, close_date, pnl, pnl_pct, hold_days, r_mult, stop_used, setup, note, created_at in rows:
        if trade_id in reviewed_trades:
            continue

        input_hash = make_hash(trade_id, symbol, str(pnl), str(close_date))
        if (symbol,) in existing:
            continue

        score = 0
        reasons = []
        tier = "P3"

        pnl_val = float(pnl) if pnl else 0

        # Large realized loss
        if pnl_val < -500:
            score += 95
            reasons.append("large_loss")
            tier = "P0"
        elif pnl_val < -100:
            score += 85
            reasons.append("loss")
            tier = "P1"

        # Large realized gain
        if pnl_val > 500:
            score += 85
            reasons.append("large_gain")
            if tier not in ("P0",):
                tier = "P1"
        elif pnl_val > 100:
            score += 70
            reasons.append("gain")

        # Stop triggered
        if stop_used and float(stop_used) > 0:
            score += 90
            reasons.append("stop_triggered")
            if tier not in ("P0",):
                tier = "P0"

        # Recent trade (within 14 days)
        if close_date:
            days_since = (datetime.now().date() - close_date).days
            if days_since <= 7:
                score += 85
                reasons.append("recent_close")
                if tier in ("P3", "P4"):
                    tier = "P1"
            elif days_since <= 14:
                score += 50
                reasons.append(f"close_{days_since}d_ago")

        # Never reviewed
        score += 30
        reasons.append("never_gemma_reviewed")

        jobs.append({
            "job_type": "closed_trade_review",
            "symbol": symbol,
            "trade_id": trade_id,
            "account": account,
            "priority_tier": tier,
            "priority_score": score,
            "reason_codes": reasons,
            "source_script": "build_deep_overnight_llm_queue.py",
            "source_table": "trade_closed",
            "input_hash": input_hash,
        })

    return jobs


def build_journal_review_jobs(cur, held_symbols):
    """Queue journal trade reviews for gemma deep analysis."""
    jobs = []

    cur.execute("""
        SELECT symbol, input_hash FROM deep_overnight_llm_queue
        WHERE job_type IN ('auto_journal_review', 'manual_journal_review')
        AND status IN ('pending', 'running')
    """)
    existing = {row[0]: row[1] for row in cur.fetchall()}

    cur.execute("""
        SELECT id, trade_key, symbol, account, closed_date, setup_name,
               well_executed, execution_quality_score, lesson_learned,
               review_notes, created_at, updated_at
        FROM journal_trade_reviews
        ORDER BY id DESC
    """)
    rows = cur.fetchall()

    cur.execute("""
        SELECT journal_id FROM deep_overnight_llm_results
        WHERE job_type IN ('auto_journal_review', 'manual_journal_review')
        AND journal_id IS NOT NULL
    """)
    reviewed = {row[0] for row in cur.fetchall()}

    for jid, trade_key, symbol, account, closed_date, setup_name, well_exec, exec_score, lesson, notes, created_at, updated_at in rows:
        if jid in reviewed:
            continue
        if symbol in existing:
            continue

        input_hash = make_hash(jid, trade_key, str(updated_at))

        score = 0
        reasons = []
        tier = "P2"

        # Poorly executed trades are high priority
        if well_exec is False:
            score += 80
            reasons.append("poorly_executed")
            tier = "P1"

        if exec_score and int(exec_score) <= 2:
            score += 75
            reasons.append("low_execution_score")
            tier = "P1"

        # Journal entries with lessons are good candidates
        if lesson:
            score += 40
            reasons.append("has_lesson")

        # Recent entries
        if created_at:
            days_old = (datetime.now(timezone.utc) - created_at).total_seconds() / 86400
            if days_old <= 7:
                score += 60
                reasons.append("recent_journal")
            elif days_old <= 14:
                score += 30
                reasons.append(f"journal_{int(days_old)}d_old")

        score += 30
        reasons.append("never_gemma_reviewed")

        # Determine if this looks like auto vs manual
        is_auto = trade_key and trade_key.startswith("auto_")
        job_type = "auto_journal_review" if is_auto else "manual_journal_review"

        jobs.append({
            "job_type": job_type,
            "symbol": symbol,
            "journal_id": jid,
            "account": account,
            "priority_tier": tier,
            "priority_score": score,
            "reason_codes": reasons,
            "source_script": "build_deep_overnight_llm_queue.py",
            "source_table": "journal_trade_reviews",
            "input_hash": input_hash,
        })

    return jobs


def build_proposal_review_jobs(cur, held_symbols):
    """Queue pending proposals for gemma deep review."""
    jobs = []

    cur.execute("""
        SELECT symbol FROM deep_overnight_llm_queue
        WHERE job_type = 'proposal_review' AND status IN ('pending', 'running')
    """)
    existing = {row[0] for row in cur.fetchall()}

    cur.execute("""
        SELECT id, symbol, created_at
        FROM paper_trade_proposals
        WHERE status IN ('pending', 'approved', 'ready')
        ORDER BY created_at DESC
        LIMIT 50
    """)
    rows = cur.fetchall()

    cur.execute("""
        SELECT trade_id FROM deep_overnight_llm_results
        WHERE job_type = 'proposal_review' AND trade_id IS NOT NULL
    """)
    reviewed = {row[0] for row in cur.fetchall()}

    for pid, symbol, created_at in rows:
        if pid in reviewed or symbol in existing:
            continue

        input_hash = make_hash(pid, symbol, str(created_at))
        score = 80
        reasons = ["pending_proposal"]
        tier = "P1"

        if symbol in held_symbols:
            score += 20
            reasons.append("held_position")

        jobs.append({
            "job_type": "proposal_review",
            "symbol": symbol,
            "trade_id": pid,
            "priority_tier": tier,
            "priority_score": score,
            "reason_codes": reasons,
            "source_script": "build_deep_overnight_llm_queue.py",
            "source_table": "paper_trade_proposals",
            "input_hash": input_hash,
        })

    return jobs


# ─── Main ────────────────────────────────────────────────────────────────

ALL_JOB_TYPES = [
    "strategy_classification",
    "closed_trade_review",
    "auto_journal_review",
    "manual_journal_review",
    "proposal_review",
]

BUILDERS = {
    "strategy_classification": build_strategy_classification_jobs,
    "closed_trade_review": build_closed_trade_review_jobs,
    "auto_journal_review": build_journal_review_jobs,
    "manual_journal_review": build_journal_review_jobs,
    "proposal_review": build_proposal_review_jobs,
}


def main():
    parser = argparse.ArgumentParser(description="Build deep overnight LLM queue")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be queued")
    parser.add_argument("--apply", action="store_true", help="Actually insert into queue")
    parser.add_argument("--limit", type=int, default=200, help="Max jobs to queue")
    parser.add_argument("--job-types", type=str, default=None,
                        help="Comma-separated job types to build")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Must specify --dry-run or --apply")
        sys.exit(1)

    held_symbols = get_held_symbols()
    print(f"Held symbols: {len(held_symbols)}")

    conn = get_db_connection()
    cur = conn.cursor()

    # Determine which job types to build
    if args.job_types:
        requested = [jt.strip() for jt in args.job_types.split(",")]
    else:
        requested = ALL_JOB_TYPES

    # Build jobs (deduplicate journal builders)
    all_jobs = []
    built_types = set()
    for jt in requested:
        builder = BUILDERS.get(jt)
        if not builder:
            print(f"WARNING: Unknown job type '{jt}', skipping")
            continue
        # Journal builders return both auto and manual, so only call once
        builder_key = id(builder)
        if builder_key in built_types:
            continue
        built_types.add(builder_key)

        try:
            jobs = builder(cur, held_symbols)
            # Filter to requested types if builder returns multiple
            jobs = [j for j in jobs if j["job_type"] in requested]
            all_jobs.extend(jobs)
            print(f"  {jt}: {len(jobs)} candidates")
        except Exception as e:
            print(f"  {jt}: ERROR — {e} (continuing)")

    # Sort by priority score descending
    all_jobs.sort(key=lambda j: j["priority_score"], reverse=True)

    # Apply limit
    if len(all_jobs) > args.limit:
        print(f"\nLimiting from {len(all_jobs)} to {args.limit} jobs")
        all_jobs = all_jobs[:args.limit]

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Total jobs to queue: {len(all_jobs)}")
    print(f"{'=' * 60}")

    # Tier breakdown
    tiers = {}
    type_counts = {}
    for j in all_jobs:
        tiers[j["priority_tier"]] = tiers.get(j["priority_tier"], 0) + 1
        type_counts[j["job_type"]] = type_counts.get(j["job_type"], 0) + 1

    print("\nBy priority tier:")
    for t in sorted(tiers.keys()):
        print(f"  {t}: {tiers[t]}")

    print("\nBy job type:")
    for jt, cnt in sorted(type_counts.items()):
        print(f"  {jt}: {cnt}")

    # Show top 50
    print(f"\nTop {min(50, len(all_jobs))} jobs:")
    print(f"{'Rank':>4} {'Type':>25} {'Symbol':>8} {'Tier':>4} {'Score':>5} {'Reasons'}")
    print("-" * 90)
    for i, j in enumerate(all_jobs[:50]):
        ident = j.get("symbol") or f"trade#{j.get('trade_id')}" or f"journal#{j.get('journal_id')}" or "—"
        reasons = ",".join(j["reason_codes"][:3])
        print(f"{i+1:>4} {j['job_type']:>25} {ident:>8} {j['priority_tier']:>4} {j['priority_score']:>5} {reasons}")

    if args.dry_run:
        print(f"\n=== DRY RUN — {len(all_jobs)} jobs would be queued ===")
        conn.close()
        return

    # Apply: insert or update
    inserted = 0
    updated = 0
    for j in all_jobs:
        # Check if already exists with same hash
        cur.execute("""
            SELECT id, priority_score, input_hash FROM deep_overnight_llm_queue
            WHERE job_type = %s AND status = 'pending'
            AND (symbol = %s OR (symbol IS NULL AND %s IS NULL))
            AND (trade_id = %s OR (trade_id IS NULL AND %s IS NULL))
            AND (journal_id = %s OR (journal_id IS NULL AND %s IS NULL))
            LIMIT 1
        """, (j["job_type"], j.get("symbol"), j.get("symbol"),
              j.get("trade_id"), j.get("trade_id"),
              j.get("journal_id"), j.get("journal_id")))
        existing = cur.fetchone()

        if existing:
            eid, old_score, old_hash = existing
            if j["input_hash"] != old_hash or j["priority_score"] > old_score:
                cur.execute("""
                    UPDATE deep_overnight_llm_queue
                    SET priority_score = GREATEST(priority_score, %s),
                        priority_tier = %s,
                        reason_codes = %s,
                        input_hash = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (j["priority_score"], j["priority_tier"],
                      j["reason_codes"], j["input_hash"], eid))
                updated += 1
        else:
            cur.execute("""
                INSERT INTO deep_overnight_llm_queue
                (job_type, symbol, trade_id, journal_id, account,
                 priority_tier, priority_score, reason_codes,
                 source_script, source_table, status, input_hash,
                 last_qwen_summary, last_qwen_confidence, metadata_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
            """, (j["job_type"], j.get("symbol"), j.get("trade_id"),
                  j.get("journal_id"), j.get("account"),
                  j["priority_tier"], j["priority_score"],
                  j["reason_codes"], j.get("source_script"),
                  j.get("source_table"), j["input_hash"],
                  j.get("last_qwen_summary"), j.get("last_qwen_confidence"),
                  json.dumps(j.get("metadata_json", {}))))
            inserted += 1

    conn.commit()

    # Final count
    cur.execute("SELECT count(*) FROM deep_overnight_llm_queue WHERE status = 'pending'")
    pending = cur.fetchone()[0]

    print(f"\n=== APPLIED ===")
    print(f"  Inserted: {inserted}")
    print(f"  Updated:  {updated}")
    print(f"  Total pending in queue: {pending}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
