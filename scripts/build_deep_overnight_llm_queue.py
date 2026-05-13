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


# ─── Phase 1H Expansion: Direct-insert queue builders ─────────────────────

def _already_queued(cur, input_hash):
    """Check if a job with this input_hash is already pending/running/done."""
    cur.execute("""
        SELECT id FROM deep_overnight_llm_queue
        WHERE input_hash = %s AND status IN ('pending', 'running', 'done')
    """, [input_hash])
    return cur.fetchone() is not None


def _insert_queue_item(cur, job_type, symbol, tier, score, reasons, input_hash,
                       source_table=None, source_id=None):
    """Insert a single queue item. Returns 1 if inserted, 0 if skipped."""
    if _already_queued(cur, input_hash):
        return 0
    cur.execute("""
        INSERT INTO deep_overnight_llm_queue
            (job_type, symbol, priority_tier, priority_score,
             reason_codes, input_hash, source_table, source_id,
             source_script, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                'build_deep_overnight_llm_queue.py', 'pending')
    """, [job_type, symbol, tier, score, reasons, input_hash,
          source_table, source_id])
    return cur.rowcount


def queue_risk_synthesis(cur, dry_run=False):
    """Queue one portfolio-level risk synthesis per night. P0, single job."""
    today = datetime.now().strftime("%Y-%m-%d")
    input_hash = f"risk_synthesis:{today}"
    if _already_queued(cur, input_hash):
        return 0
    if dry_run:
        print(f"  [DRY] risk_synthesis: PORTFOLIO nightly score=100")
        return 1
    return _insert_queue_item(cur, "risk_synthesis", "PORTFOLIO", "P0", 100,
                              ["nightly_synthesis"], input_hash)


def queue_rag_content_curation(cur, dry_run=False):
    """Queue pending/low-quality content for gemma deep curation. Up to 20/night."""
    queued = 0

    # Pending news > 48h old
    cur.execute("""
        SELECT id, title, symbol
        FROM news_articles
        WHERE rag_status = 'pending'
          AND published_at < NOW() - INTERVAL '48 hours'
          AND deep_curation_at IS NULL
        ORDER BY published_at DESC LIMIT 12
    """)
    for aid, title, symbol in cur.fetchall():
        ih = f"rag_curation:news_articles:{aid}"
        if dry_run:
            print(f"  [DRY] rag_curation: news:{aid} '{(title or '')[:40]}' score=75")
            queued += 1
        else:
            queued += _insert_queue_item(cur, "rag_content_curation", symbol or "",
                                         "P1", 75, ["pending_news", "age>48h"], ih,
                                         "news_articles", aid)
        if queued >= 20:
            return queued

    # Low-quality news never gemma-reviewed
    cur.execute("""
        SELECT id, title, symbol
        FROM news_articles
        WHERE rag_status = 'low_quality' AND deep_curation_at IS NULL
        ORDER BY published_at DESC LIMIT 8
    """)
    for aid, title, symbol in cur.fetchall():
        ih = f"rag_curation:news_articles:{aid}"
        if dry_run:
            print(f"  [DRY] rag_curation: news_low:{aid} '{(title or '')[:40]}' score=65")
            queued += 1
        else:
            queued += _insert_queue_item(cur, "rag_content_curation", symbol or "",
                                         "P1", 65, ["low_quality_news"], ih,
                                         "news_articles", aid)
        if queued >= 20:
            return queued

    # YouTube transcripts pending/low
    cur.execute("""
        SELECT id, COALESCE(title, channel_name) as title
        FROM youtube_transcripts
        WHERE rag_status IN ('pending', 'low_quality') AND deep_curation_at IS NULL
        ORDER BY created_at DESC LIMIT 8
    """)
    for tid, title in cur.fetchall():
        ih = f"rag_curation:youtube_transcripts:{tid}"
        if dry_run:
            print(f"  [DRY] rag_curation: yt:{tid} '{(title or '')[:40]}' score=70")
            queued += 1
        else:
            queued += _insert_queue_item(cur, "rag_content_curation", "",
                                         "P1", 70, ["pending_transcript"], ih,
                                         "youtube_transcripts", tid)
        if queued >= 20:
            return queued

    return queued


def queue_recovery_watch_review(cur, dry_run=False):
    """Queue recovery watch reviews. Tue/Thu only."""
    if datetime.now().weekday() not in (1, 3):  # Tue=1, Thu=3
        return 0

    week_tag = datetime.now().strftime("%Y-%W")
    cur.execute("""
        SELECT symbol, status, exit_price, stopped_out_at, thesis_at_exit
        FROM stopped_out_watch
        WHERE is_active = true
        ORDER BY stopped_out_at DESC LIMIT 12
    """)
    queued = 0
    for symbol, status, exit_price, stopped_at, thesis in cur.fetchall():
        ih = f"recovery_watch:{symbol}:{week_tag}"
        score = 90
        reasons = [f"status:{status}"]
        if dry_run:
            print(f"  [DRY] recovery_watch: {symbol} status={status} score={score}")
            queued += 1
        else:
            queued += _insert_queue_item(cur, "recovery_watch_review", symbol,
                                         "P1", score, reasons, ih,
                                         "stopped_out_watch", None)
    return queued


def queue_covered_call_scoring(cur, dry_run=False):
    """Queue covered call scoring. Sunday only."""
    if datetime.now().weekday() != 6:  # Sunday=6
        return 0

    week_tag = datetime.now().strftime("%Y-%W")
    cur.execute("""
        SELECT symbol, recommendation, confidence_score
        FROM aegis_covered_call_candidates
        WHERE recommendation IN ('review_needed', 'candidate')
        ORDER BY confidence_score DESC NULLS LAST LIMIT 15
    """)
    queued = 0
    for symbol, rec, conf in cur.fetchall():
        ih = f"cc_scoring:{symbol}:{week_tag}"
        score = 80 + (10 if rec == "candidate" else 0)
        if dry_run:
            print(f"  [DRY] covered_call: {symbol} rec={rec} score={score}")
            queued += 1
        else:
            queued += _insert_queue_item(cur, "covered_call_scoring", symbol,
                                         "P1", score, [f"cc_rec:{rec}"], ih,
                                         "aegis_covered_call_candidates", None)
    return queued


def queue_weekly_behavioral_review(cur, dry_run=False):
    """Queue weekly behavioral review. Sunday only. Gated at 20+ closed trades."""
    if datetime.now().weekday() != 6:
        return 0

    cur.execute("SELECT COUNT(*) FROM paper_trades WHERE lifecycle_state = 'closed'")
    closed = cur.fetchone()[0]
    if closed < 20:
        print(f"  [SKIP] weekly_behavioral: {closed} closed trades, need 20+")
        return 0

    week_tag = datetime.now().strftime("%Y-%W")
    ih = f"weekly_behavior:{week_tag}"
    if dry_run:
        print(f"  [DRY] weekly_behavioral: {closed} closed trades score=55")
        return 1
    return _insert_queue_item(cur, "weekly_behavioral_review", "ALL_TRADES",
                              "P2", 55, [f"closed:{closed}"], ih)


def queue_rebalance_analysis(cur, dry_run=False):
    """Queue monthly deep rebalance analysis. 1st of month or stale >35d."""
    today = datetime.now()

    # Check if already done this month
    cur.execute("""
        SELECT id FROM rebalance_analysis_results
        WHERE analysis_tier = 'gemma3_monthly'
          AND generated_at > DATE_TRUNC('month', NOW())
        LIMIT 1
    """)
    if cur.fetchone():
        return 0

    # Check staleness
    cur.execute("""
        SELECT generated_at FROM rebalance_analysis_results
        WHERE analysis_tier = 'gemma3_monthly'
        ORDER BY generated_at DESC LIMIT 1
    """)
    row = cur.fetchone()
    stale_days = (datetime.now() - row[0].replace(tzinfo=None)).days if row else 999

    is_first = (today.day == 1)
    is_stale = (stale_days > 35)
    if not (is_first or is_stale):
        return 0

    ih = f"rebalance_analysis:{today.strftime('%Y-%m')}"
    if _already_queued(cur, ih):
        return 0

    reason = "monthly_1st" if is_first else f"stale_{stale_days}d"
    if dry_run:
        print(f"  [DRY] rebalance_analysis: PORTFOLIO reason={reason} stale={stale_days}d score=95")
        return 1
    return _insert_queue_item(cur, "rebalance_analysis", "PORTFOLIO",
                              "P0", 95, [reason], ih)


EXPANSION_BUILDERS = [
    ("risk_synthesis", queue_risk_synthesis),
    ("rag_content_curation", queue_rag_content_curation),
    ("recovery_watch_review", queue_recovery_watch_review),
    ("covered_call_scoring", queue_covered_call_scoring),
    ("weekly_behavioral_review", queue_weekly_behavioral_review),
    ("rebalance_analysis", queue_rebalance_analysis),
]


# ─── Main ────────────────────────────────────────────────────────────────

ALL_JOB_TYPES = [
    "strategy_classification",
    "closed_trade_review",
    "auto_journal_review",
    "manual_journal_review",
    "proposal_review",
    "risk_synthesis",
    "rag_content_curation",
    "recovery_watch_review",
    "covered_call_scoring",
    "weekly_behavioral_review",
    "rebalance_analysis",
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

    # ── Phase 1H expansion: direct-insert builders ──
    expansion_total = 0
    for exp_name, exp_fn in EXPANSION_BUILDERS:
        if args.job_types and exp_name not in requested:
            continue
        try:
            n = exp_fn(cur, dry_run=args.dry_run)
            if n > 0:
                print(f"  {exp_name}: {n} queued")
                expansion_total += n
            if not args.dry_run:
                conn.commit()
        except Exception as e:
            print(f"  {exp_name}: ERROR — {e} (continuing)")

    if expansion_total:
        print(f"\nExpansion job types: {expansion_total} additional items")

    if args.dry_run:
        print(f"\n=== DRY RUN — {len(all_jobs)} list jobs + {expansion_total} expansion jobs ===")
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
