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
import pathlib
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

# ── Declarative registry (2026-10-07) ─────────────────────────────
# config/data_retention_policy.json is the governed source of truth (CI gate:
# scripts/check_retention_policy.py). POLICIES above is retained as documentation of the
# inherited list; the run loop uses the registry. KEEP_FOREVER rows are never deleted;
# ARCHIVE_THEN_DELETE rows are copied to persistent-state/archive/db_retention/<table>/
# as jsonl.gz BEFORE the delete, and the delete runs only when the archived row count
# equals the matching count. A missing or malformed registry stops the run loudly.
REGISTRY_PATH = _os.getenv("TRADEAI_RETENTION_REGISTRY") or str(
    __import__("pathlib").Path(__file__).resolve().parent.parent / "config" / "data_retention_policy.json")


def load_registry(path: str | None = None) -> dict:
    import json as _json
    from pathlib import Path as _P
    doc = _json.loads(_P(path or REGISTRY_PATH).read_text(encoding="utf-8"))
    if doc.get("schema") != "DataRetentionPolicy@v1" or not isinstance(doc.get("policies"), list):
        raise SystemExit("ERROR: retention registry malformed (schema DataRetentionPolicy@v1 required)")
    return doc


def enforced_policies(doc: dict) -> list[tuple[str, str, int, bool]]:
    """(table, column, days, archive_first) for rows the run loop may delete from."""
    out = []
    for r in doc["policies"]:
        cls = r.get("class")
        if cls in ("KEEP_FOREVER", "EXTERNAL_POLICY"):
            continue
        if cls not in ("DELETE", "ARCHIVE_THEN_DELETE"):
            raise SystemExit(f"ERROR: registry row {r.get('table')} has unknown class {cls!r}")
        out.append((r["table"], r["ts_column"], int(r["window_days"]), cls == "ARCHIVE_THEN_DELETE"))
    return out


def archive_root() -> "pathlib.Path":
    from pathlib import Path as _P
    base = _os.getenv("TRADEAI_STATE_ROOT")
    root = _P(base) if base else _P.home() / "trade-ai-releases" / "persistent-state"
    return root / "archive" / "db_retention"


def archive_rows(cur, table: str, col: str, days: int, guard: str) -> tuple[int, str]:
    """Write the rows about to be deleted to <archive>/<table>/<UTC date>.jsonl.gz. Returns (rows, path)."""
    import gzip, json as _json
    from datetime import timezone as _tz
    d = archive_root() / table
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"{stamp}.jsonl.gz"
    cur.execute(f"SELECT row_to_json(t) FROM {table} t WHERE t.{col} < now() - interval '{days} days'{guard}")
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for (row,) in cur:
            fh.write(_json.dumps(row, default=str) + "\n")
            n += 1
    if n == 0:
        path.unlink(missing_ok=True)
    else:
        # 2026-10-09: every archive carries a row count + sha256 manifest (RetentionArchiveManifest@v1).
        _ra = _retention_archive()
        _ra.write_manifest(path, table=table, rows=n, sha256=_ra._sha256_file(path), bytes=path.stat().st_size,
                           predicate=f"{col} < now() - interval '{days} days'")
    return n, str(path)


def _retention_archive():
    from pathlib import Path as _P
    _scripts = str(_P(__file__).resolve().parent)
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    from lib import retention_archive
    return retention_archive


# ── Per-source windows (2026-10-09, operator decision) ────────────
# A registry row may declare `source_windows` {value: days} over `source_column`: rows of that
# source older than its window are ARCHIVE_THEN_DELETE'd in verified batches (archive re-read for
# row count + sha256 before each batch's DELETE), capped per run so a backlog converges over
# several nights inside the step's timeout. Storage audit 2026-10-09: content_embeddings declared
# {fused_signal: 30, social_post: 30} on 2026-10-07 and no code read it.
DEFAULT_SOURCE_BATCH_ROWS = 20000
DEFAULT_SOURCE_MAX_ROWS_PER_RUN = 100000


def enforced_source_windows(doc: dict) -> list[dict]:
    out = []
    for r in doc["policies"]:
        sw = r.get("source_windows")
        if not sw or r.get("class") in ("KEEP_FOREVER", "EXTERNAL_POLICY"):
            continue
        if r.get("source_windows_class") != "ARCHIVE_THEN_DELETE" or not r.get("source_column"):
            raise SystemExit(f"ERROR: registry row {r.get('table')} source_windows needs source_column and "
                             "source_windows_class ARCHIVE_THEN_DELETE")
        for value, days in sorted(sw.items()):
            out.append({"table": r["table"], "ts_column": r["ts_column"], "source_column": r["source_column"],
                        "source": value, "days": int(days),
                        "batch_rows": int(r.get("source_windows_batch_rows") or DEFAULT_SOURCE_BATCH_ROWS),
                        "max_rows": int(r.get("source_windows_max_rows_per_run") or DEFAULT_SOURCE_MAX_ROWS_PER_RUN)})
    return out


def source_window_predicate(w: dict, guard: str = "") -> tuple[str, tuple]:
    return (f't."{w["source_column"]}" = %s AND t."{w["ts_column"]}" < now() - make_interval(days => %s){guard}',
            (w["source"], int(w["days"])))


def run_source_windows(cur, conn, windows: list[dict], dry_run: bool) -> tuple[int, list[str]]:
    """Returns (rows deleted or would-delete, failed labels)."""
    ra = _retention_archive()
    total, failed = 0, []
    for w in windows:
        label = f"{w['table']}.{w['source']}"
        try:
            guard = fk_guard(cur, w["table"])
            where, params = source_window_predicate(w, guard)
            if dry_run:
                cur.execute(f"SELECT count(*) FROM {w['table']} t WHERE {where}", params)
                n = cur.fetchone()[0]
                print(f"  {label:<43} {w['ts_column']:<18} {w['days']:>5}  {n:>8}  (source window, archive-first;"
                      f" per-run cap {w['max_rows']:,})")
                total += min(n, w["max_rows"])
                continue
            res = ra.archive_then_delete_batches(
                conn, table=w["table"], where_sql=where, params=params,
                label=f"source_window_{w['source']}", archive_dir=archive_root() / w["table"],
                batch_rows=w["batch_rows"], max_rows=w["max_rows"])
            total += res["rows_deleted"]
            print(f"  {label:<43} {w['ts_column']:<18} {w['days']:>5}  {res['rows_deleted']:>8}  (archived "
                  f"{res['rows_archived']:,} in {len(res['batches'])} verified batch(es)"
                  f"{'; per-run cap reached' if res.get('cap_reached') else ''})")
        except Exception as e:
            conn.rollback()
            failed.append(label)
            print(f"  ERROR: {label}: {e}")
    return total, failed


# ── One-time: degenerate fused_signal embeddings (2026-10-09, operator decision) ──
# rag_indexer embedded fused_signals as "SYM signal  severity:low" because signal_fusion.py never
# writes `direction`; the stored title is the blank template "SYM signal: ". 958,071 rows, ~14
# distinct vectors. Separately invoked, dry run by default; --apply archives each batch, re-reads
# it (row count + sha256 + key set) and only then deletes it. Run only AFTER the rag_indexer text
# fix is served, or the old indexer re-embeds the same junk.
JUNK_FUSED_TITLE_RE = r"^\S+ signal: *$"
JUNK_FUSED_WHERE = "t.source_type = 'fused_signal' AND t.title ~ %s"


def purge_junk_fused_embeddings(apply: bool = False, batch_rows: int = DEFAULT_SOURCE_BATCH_ROWS,
                                max_rows: int = 200000, sample_rows: int = 500) -> int:
    import json as _json
    from datetime import timezone as _tz
    ra = _retention_archive()
    stamp = datetime.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {"schema": "JunkFusedEmbeddingPurgeReceipt@v1", "stamp": stamp, "apply": bool(apply),
               "table": "content_embeddings", "predicate": JUNK_FUSED_WHERE, "title_regex": JUNK_FUSED_TITLE_RE,
               "batch_rows": int(batch_rows), "max_rows_per_run": int(max_rows)}
    if apply:
        blocked = _disk_too_low_for_retention()
        if blocked:
            receipt.update(status="refused", reason=f"disk below critical floor: {blocked}")
            print(_json.dumps(receipt, indent=1, default=str))
            return 2
    conn = _connect()
    code = 0
    try:
        receipt["before"] = ra.estimate(conn, table="content_embeddings", where_sql=JUNK_FUSED_WHERE,
                                        params=(JUNK_FUSED_TITLE_RE,), sample_rows=sample_rows)
        conn.rollback()
        if not apply:
            receipt["status"] = "dry_run"
            b = receipt["before"]
            print(f"DRY RUN — junk fused_signal embeddings: {b['rows']:,} rows, {b['stored_bytes']:,} B stored, "
                  f"est. archive {b['est_archive_bytes'] or 0:,} B; this run would archive+delete up to "
                  f"{min(b['rows'], int(max_rows)):,} in batches of {int(batch_rows):,}")
        else:
            try:
                res = ra.archive_then_delete_batches(
                    conn, table="content_embeddings", where_sql=JUNK_FUSED_WHERE, params=(JUNK_FUSED_TITLE_RE,),
                    label="junk_fused_signal", archive_dir=archive_root() / "content_embeddings",
                    batch_rows=int(batch_rows), max_rows=int(max_rows), stamp=stamp)
                receipt.update(status="ok", result=res)
            except Exception as e:
                conn.rollback()
                receipt.update(status="failed", error=f"{type(e).__name__}: {e}")
                code = 1
            receipt["remaining"] = ra.estimate(conn, table="content_embeddings", where_sql=JUNK_FUSED_WHERE,
                                               params=(JUNK_FUSED_TITLE_RE,), sample_rows=0)["rows"]
            conn.rollback()
            rdir = archive_root() / "content_embeddings" / "receipts"
            rdir.mkdir(parents=True, exist_ok=True)
            rpath = rdir / f"{stamp}-junk_fused_signal.json"
            rpath.write_text(_json.dumps(receipt, indent=1, default=str, sort_keys=True) + "\n", encoding="utf-8")
            receipt["receipt_path"] = str(rpath)
    finally:
        conn.close()
    print(_json.dumps(receipt, indent=1, default=str, sort_keys=True))
    return code


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

    registry = load_registry()
    enforced = enforced_policies(registry)
    kept = [r["table"] for r in registry["policies"] if r.get("class") == "KEEP_FOREVER"]
    print(f"  registry {REGISTRY_PATH}: {len(enforced)} enforced, {len(kept)} KEEP_FOREVER ({', '.join(kept)})")
    archived_total = 0
    for table, col, days, archive_first in enforced:
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
            cur.execute(f"SELECT count(*) FROM {table} t WHERE t.{col} < now() - interval '{days} days'{guard}")
            matching = cur.fetchone()[0]
            if dry_run:
                count = matching
            else:
                if archive_first and matching > 0:
                    n_arch, path = archive_rows(cur, table, col, days, guard)
                    if n_arch != matching:
                        raise RuntimeError(f"archived {n_arch} != matching {matching}; delete refused (archive {path})")
                    archived_total += n_arch
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

    sw_total, sw_failed = run_source_windows(cur, conn, enforced_source_windows(registry), dry_run)
    total_deleted += sw_total
    failures.extend(sw_failed)

    print("-" * 82)
    print(f"  Total {'would delete' if dry_run else 'deleted'}: {total_deleted:,} rows; archived first: {archived_total:,}"
          f" (+{sw_total:,} source-window rows, archive-first)")
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
    parser.add_argument("--junk-fused-signal-embeddings", action="store_true",
                        help="ONE-TIME mode: archive-then-delete content_embeddings fused_signal rows whose title is "
                             "the blank template 'SYM signal: '. Dry run unless --apply. Nothing else runs.")
    parser.add_argument("--apply", action="store_true", help="with --junk-fused-signal-embeddings: archive, verify, delete")
    parser.add_argument("--batch-rows", type=int, default=DEFAULT_SOURCE_BATCH_ROWS)
    parser.add_argument("--max-rows", type=int, default=200000, help="per-run cap for the one-time mode")
    args = parser.parse_args()
    if args.junk_fused_signal_embeddings:
        raise SystemExit(purge_junk_fused_embeddings(apply=args.apply and not args.dry_run,
                                                     batch_rows=args.batch_rows, max_rows=args.max_rows))
    if args.apply:
        raise SystemExit("ERROR: --apply is only for --junk-fused-signal-embeddings (the nightly run applies by default)")
    raise SystemExit(run(dry_run=args.dry_run))
