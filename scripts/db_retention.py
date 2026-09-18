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

    # An empty password is NOT a valid credential -- libpq quietly falls back to
    # ~/.pgpass, and the resulting failure blames "password authentication failed"
    # while naming a file nobody meant to use. Same defect as the one fixed in
    # watch_decision_refresh.py. Refuse, and say which source was empty, so a
    # retention run that cannot connect is never mistaken for one with nothing
    # to prune.
    if not _os.getenv("DB_PASSWORD") and "password=" in DB_DSN and "password= " not in DB_DSN:
        if DB_DSN.split("password=", 1)[1].strip() == "":
            raise SystemExit(
                "ERROR: DB_PASSWORD is empty. Set it, or run from a tree whose .env "
                "resolves (the render is at /run/user/$UID/tradeai/env). Refusing to "
                "let libpq fall back to ~/.pgpass."
            )
    return psycopg2.connect(DB_DSN)

# ── Retention policies ───────────────────────────────────────────
# Format: (table_name, date_column, retention_days)

POLICIES = [
    # PRICE tier — 1 year
    ("price_cache",                     "price_date",      365),
    ("ticker_prices",                   "price_date",      365),

    # LONG tier — 180 days
    # Archive of the 130,155 rows the Finviz column shift fabricated: index 10 of
    # view 141 was labelled "recom" and actually carried Performance (10 Years),
    # so a stock down -100% published as "Strong Buy". Quarantined 2026-09-13;
    # the live columns were nulled and this holds the originals.
    #
    # Keyed on quarantined_at, NOT created_at. The archived rows carry their
    # ORIGINAL created_at (2026-04-20 onward), so a created_at window would have
    # started deleting the evidence about 34 days from now rather than 180. The
    # window that matters is time since quarantine, which is what
    # quarantined_at (added with DEFAULT now()) measures. Purges 2027-03-12.
    #
    # Until then this is the reversal path -- the UPDATE in
    # scripts/quarantine_fabricated_analyst_ratings.py restores every value from
    # here. Six months is deliberately longer than any window in which the
    # diagnosis might be found wrong.
    ("analyst_consensus_history_quarantine_20260913", "quarantined_at", 180),
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

    # EPHEMERAL / regenerative streams & caches (2026-08-11 storage audit)
    # These were top disk consumers and missing from POLICIES — easily re-captured.
    ("schwab_stream_book",              "captured_at",       7),
    ("schwab_stream_quotes",            "captured_at",       7),
    ("hermes_score_history",            "scored_at",        21),
    ("scope_governor_audit",            "created_at",       30),
    ("system_health_checks",            "created_at",       30),
    ("hermes_discovery_audit",          "created_at",       30),

    # VECTOR / RAG store — largest table (~10GB observed 2026-09-10). Regenerable.
    # Librarian policy orphan_purge_days=30; age cap prevents unbounded growth when
    # orphan detection is not yet wired into this script.
    ("content_embeddings",             "created_at",      180),
]
# Note: market_quotes already in MEDIUM tier (90d) above.


def fk_guard(cur, table: str) -> str:
    """SQL that keeps rows another table still references out of the purge.

    2026-09-14: aegis_steph_escalations (1,212 expired rows) and
    watchlist_agent_jobs (69,248) were never pruned: the single DELETE aborted on
    3 and 6 rows still referenced by a child table, so the whole policy failed
    every night. Expired rows nothing references are deleted; referenced rows
    wait until their children expire under their own policy. Single-column
    foreign keys only; anything else keeps the old statement (and its loud error).
    Operator decision the same day: retention may keep hard-deleting.
    """
    cur.execute("""
        SELECT c.conrelid::regclass::text, a.attname, af.attname
        FROM pg_constraint c
        JOIN pg_attribute a  ON a.attrelid = c.conrelid  AND a.attnum = c.conkey[1]
        JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = c.confkey[1]
        WHERE c.contype = 'f' AND c.confrelid = %s::regclass
          AND array_length(c.conkey, 1) = 1
    """, (table,))
    parts = []
    for child, child_col, parent_col in cur.fetchall():
        parts.append(f' AND NOT EXISTS (SELECT 1 FROM {child} ch WHERE ch."{child_col}" = t."{parent_col}")')
    return "".join(parts)


def _disk_too_low_for_retention():
    """Skip DELETEs when free space is already critical — WAL for large deletes
    is what PANICed postgres on 2026-09-18 (schwab_stream_book cleanup under ENOSPC).
    """
    try:
        import shutil
        from pathlib import Path as _Path

        sys.path.insert(0, str(_Path(__file__).resolve().parent))
        from lib.postgres_main_health import evaluate_disk_usage, DEFAULT_DISK_CFG

        u = shutil.disk_usage("/")
        # Use critical floors only; warn band still allows retention.
        cfg = {
            **DEFAULT_DISK_CFG,
            "warn_free_pct": DEFAULT_DISK_CFG["crit_free_pct"],
            "warn_free_gb": DEFAULT_DISK_CFG["crit_free_gb"],
        }
        v = evaluate_disk_usage(
            total_bytes=u.total, used_bytes=u.used, free_bytes=u.free, cfg=cfg
        )
        if v.severity == "critical":
            return v.message
    except Exception:
        return None
    return None


def run(dry_run: bool = False):
    blocked = _disk_too_low_for_retention()
    if blocked and not dry_run:
        print(f"SKIP retention — disk below critical floor: {blocked}")
        print("Free space first, then re-run. Refusing DELETEs that need WAL under ENOSPC.")
        return {"ok": False, "skipped": True, "reason": blocked, "deleted": 0}

    conn = _connect()
    cur = conn.cursor()
    total_deleted = 0
    failures: list[str] = []

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

            guard = fk_guard(cur, table)
            if dry_run:
                cur.execute(f"SELECT count(*) FROM {table} t WHERE t.{col} < now() - interval '{days} days'{guard}")
                count = cur.fetchone()[0]
            else:
                cur.execute(f"DELETE FROM {table} t WHERE t.{col} < now() - interval '{days} days'{guard}")
                count = cur.rowcount
                conn.commit()

            if count > 0:
                total_deleted += count
                print(f"  {table:<43} {col:<18} {days:>5}  {count:>8}")
        except Exception as e:
            conn.rollback()
            failures.append(table)
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

    # A table that errors is a policy that is NOT being enforced. This used to
    # print ERROR and still exit 0, so aegis_steph_escalations and
    # watchlist_agent_jobs had been failing their foreign-key deletes on EVERY
    # run, unpruned and unreported, while systemd logged a clean success. Exit
    # code 0 is not evidence of work -- AGENTS.md rule 8.
    if failures:
        print("")
        print(f"  RETENTION NOT ENFORCED on {len(failures)} table(s): {', '.join(sorted(failures))}")
        print("  These policies did not run. Exiting non-zero so the failure is visible.")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enforce DB retention policies")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run))
