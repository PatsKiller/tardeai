#!/usr/bin/env python3
"""
db_retention.py — Database retention policy enforcement

Deletes old rows from history/cache/state tables to prevent unbounded growth.
Run via cron or manually: python scripts/db_retention.py [--dry-run]

Retention tiers:
  - PRICE:   1 year   (historical price data for performance calcs)
  - LONG:    180 days (trade history, performance, intelligence)
  - MEDIUM:  90 days  (scans, snapshots, state, agent results)
  - SHORT:   30 days  (events, jobs, queues, logs)
  - TINY:    14 days  (ephemeral caches, metrics)

Safe: never touches config/reference tables (agent_skills, strategy_registry, etc.)
"""
import argparse

# --- .env autoload (no hardcoded secrets) ---
import os as _os
if not _os.getenv("DB_PASSWORD"):
    try:
        from pathlib import Path as _P
        for _l in (_P(__file__).resolve().parent.parent / ".env").read_text().splitlines():
            if _l.startswith("DB_PASSWORD="): _os.environ["DB_PASSWORD"] = _l.split("=",1)[1].strip()
    except Exception: pass
import os
import sys
from datetime import datetime

# ── DB connection ────────────────────────────────────────────────
DB_DSN = os.getenv("TRADE_AI_DSN", f"host=localhost port=5432 dbname=trade_ai user=trade_ai password={_os.getenv('DB_PASSWORD','')}")

def _connect():
    import psycopg2
    return psycopg2.connect(DB_DSN)

# ── Retention policies ───────────────────────────────────────────
# Format: (table_name, date_column, retention_days)
#
# COVERAGE GAP (human decision required — not auto-deleted by Iris Mode 5):
#   • content_embeddings (~multi-GB RAG index) — no age policy here; Iris Storage
#     Steward handles verified-safe orphans/duplicates only. Remaining growth and
#     age-based compaction need an explicit operator policy tier.
#   • schwab_stream_book / schwab_stream_quotes — live market stream tables; any
#     retention window must be chosen against replay/debug needs, not content curation.

POLICIES = [
    # PRICE tier — 1 year
    ("price_cache",                     "price_date",      365),
    ("ticker_prices",                   "price_date",      365),

    # LONG tier — 180 days
    ("trade_transactions",              "created_at",      180),
    ("trade_closed",                    "created_at",      180),
    ("performance_daily",               "created_at",      180),
    ("dividend_history",                "created_at",      180),
    ("portfolio_snapshots",             "created_at",      180),
    ("asset_intelligence_history",      "created_at",      180),
    ("analyst_data_history",            "created_at",      180),
    ("analyst_consensus_history",       "created_at",      180),
    ("yahoo_analyst_targets_history",   "created_at",      180),
    ("transcript_intel_history",        "observed_at",     180),

    # MEDIUM tier — 90 days
    ("trade_ai_scans",                  "scanned_at",       90),
    ("trade_ai_state",                  "created_at",       90),
    ("ticker_snapshot_daily",           "snapshot_date",    90),
    ("run_summary",                     "created_at",       90),
    ("action_signals_history",          "created_at",       90),
    ("social_posts",                    "ingested_at",      90),
    ("social_sentiment_history",        "observed_at",      90),
    ("news_articles",                   "published_at",     90),
    ("article_index",                   "ingested_at",      90),
    ("catalyst_events",                 "created_at",       90),
    ("aegis_portfolio_briefs",          "observed_at",      90),
    ("aegis_symbol_snapshot_nightly",   "observed_at",      90),
    ("aegis_discovery_index",           "observed_at",      90),
    ("aegis_covered_call_candidates",   "observed_at",      90),
    ("aegis_evidence_ledger",           "observed_at",      90),
    ("aegis_steph_escalations",         "observed_at",      90),
    ("aegis_rotation_candidates",       "observed_at",      90),
    ("decision_inputs",                 "created_at",       90),
    ("decision_outcomes",               "created_at",       90),
    ("cio_decisions",                   "created_at",       90),
    ("watchlist_strategy_cards",        "updated_at",       90),
    ("watchlist_research_cards",        "updated_at",       90),
    ("watchlist_final_synthesis",       "created_at",       90),
    ("watchlist_analysis_maturity",     "created_at",       90),
    ("intelligence_whiteboard",         "created_at",       90),
    ("signal_history",                  "created_at",       90),
    ("fused_signals",                   "created_at",       90),
    ("strategy_rule_history",           "created_at",       90),
    ("strategy_rule_evaluations",       "updated_at",       90),
    ("market_quotes",                   "fetched_at",       90),
    ("sec_form4",                       "created_at",       90),
    ("research_insights",               "created_at",       90),
    ("advisor_observations",            "observed_at",      90),
    ("sentiment_observations",          "created_at",       90),
    ("state_freshness_history",         "created_at",       90),

    # SHORT tier — 30 days
    ("watchlist_events",                "created_at",       30),
    ("watchlist_agent_jobs",            "created_at",       30),
    ("watchlist_agent_results",         "created_at",       30),
    ("watchlist_synthesis_safety_history", "created_at",    30),
    ("agent_handoffs",                  "created_at",       30),
    ("agent_event_queue",               "created_at",       30),
    ("agent_chain_runs",                "created_at",       30),
    ("agent_context_refreshes",         "created_at",       30),
    ("alert_events",                    "created_at",       30),
    ("notification_log",                "created_at",       30),
    ("portfolio_intelligence_events",   "created_at",       30),
    ("escalation_queue",                "created_at",       30),
    ("john_decision_queue",             "created_at",       30),
    ("john_decision_history",           "changed_at",       30),
    ("approval_log",                    "created_at",       30),

    # TINY tier — 14 days
    ("daily_system_metrics",            "created_at",       14),
    ("daily_snapshots",                 "created_at",       14),
    ("trade_backtest_results",          "computed_at",      14),
    ("iris_run_log",                    "ran_at",           14),
    ("iris_hygiene_log",                "created_at",       14),
    ("iris_hygiene_pending",            "created_at",       14),
]


def run(dry_run: bool = False):
    conn = _connect()
    cur = conn.cursor()
    total_deleted = 0

    print(f"{'DRY RUN — ' if dry_run else ''}DB Retention Policy — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'Table':<45} {'Column':<18} {'Days':>5}  {'Deleted':>8}")
    print("-" * 82)

    for table, col, days in POLICIES:
        try:
            # Check table exists
            cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s", (table,))
            if not cur.fetchone():
                continue

            # Check column exists
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s", (table, col))
            if not cur.fetchone():
                print(f"  WARN: {table}.{col} column not found — skipping")
                continue

            if dry_run:
                cur.execute(f"SELECT count(*) FROM {table} WHERE {col} < now() - interval '{days} days'")
                count = cur.fetchone()[0]
            else:
                cur.execute(f"DELETE FROM {table} WHERE {col} < now() - interval '{days} days'")
                count = cur.rowcount
                conn.commit()

            if count > 0:
                total_deleted += count
                print(f"  {table:<43} {col:<18} {days:>5}  {count:>8}")
        except Exception as e:
            conn.rollback()
            print(f"  ERROR: {table}: {e}")

    print("-" * 82)
    print(f"  Total {'would delete' if dry_run else 'deleted'}: {total_deleted:,} rows")
    cur.close()
    conn.close()

    # ── File pruning ─────────────────────────────────────────────
    import glob, pathlib
    project = pathlib.Path(os.getenv("PROJECT_ROOT", "."))
    FILE_PRUNE = [
        (project / "data/portfolios/state/raw_snapshots", "*.json", 14),
        (project / "data/portfolios/state/ticker_snapshot_history", "*.json", 14),
        (project / "data/logs", "ingestion_summary_*.json", 7),
        (project / "data", "catalyst_cache_*.json", 3),
    ]
    print(f"\n{'DRY RUN — ' if dry_run else ''}File Pruning")
    print(f"{'Directory':<55} {'Pattern':<25} {'Days':>5}  {'Pruned':>8}")
    print("-" * 98)
    total_pruned = 0
    for directory, pattern, days in FILE_PRUNE:
        if not directory.is_dir():
            continue
        import time
        cutoff = time.time() - days * 86400
        files = list(directory.glob(pattern))
        old = [f for f in files if f.stat().st_mtime < cutoff]
        if old:
            if not dry_run:
                for f in old:
                    f.unlink()
            total_pruned += len(old)
            print(f"  {str(directory):<53} {pattern:<25} {days:>5}  {len(old):>8}")
    print("-" * 98)
    print(f"  Total {'would prune' if dry_run else 'pruned'}: {total_pruned:,} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enforce DB retention policies")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
