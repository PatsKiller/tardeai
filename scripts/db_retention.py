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
import re
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
# 2026-10-11: every archive file also gets a tripwire record (<table>/TRIPWIRE.jsonl, written by
# lib/retention_archive.write_manifest); lib/retention_tripwire.py reads it nightly through
# report_db_hygiene.py. DELETE rows may opt in to the same path with archive_first: true.
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
    """(table, column, days, archive_first) for rows the run loop may delete from.

    2026-10-11: a DELETE row may carry ``archive_first: true`` -- the same archive + manifest +
    tripwire + count-equality path as ARCHIVE_THEN_DELETE, switched per row so a large regenerable
    table (content_embeddings) can be moved to archive-first by a one-line registry change. The
    flag defaults OFF (absent/false = the inherited hard DELETE). db_retention runs from CURRENT and
    reads CURRENT's registry, so flipping it changes nothing live until a release ships it.
    """
    out = []
    for r in doc["policies"]:
        cls = r.get("class")
        if cls in ("KEEP_FOREVER", "EXTERNAL_POLICY"):
            continue
        if cls not in ("DELETE", "ARCHIVE_THEN_DELETE"):
            raise SystemExit(f"ERROR: registry row {r.get('table')} has unknown class {cls!r}")
        archive_first = cls == "ARCHIVE_THEN_DELETE" or r.get("archive_first") is True
        out.append((r["table"], r["ts_column"], int(r["window_days"]), archive_first))
    return out


def archive_root() -> "pathlib.Path":
    """<state>/archive/db_retention (one definition: lib/retention_archive.archive_root)."""
    return _retention_archive().archive_root()


def archive_rows(cur, table: str, col: str, days: int, guard: str, conn=None) -> tuple[int, str]:
    """Write the rows about to be deleted to <archive>/<table>/<UTC stamp>.jsonl.gz. Returns (rows, path).

    2026-10-11 (retention-all-managed): rows stream through a server-side cursor when ``conn`` is given
    (a 90 d content_embeddings night is ~14k rows of ~9 KB; a client-side fetch held all of it in memory),
    and the file is RE-READ from disk (sha256 + row count against the manifest) before the caller may
    delete. A failed re-read raises: the caller rolls back and nothing is deleted.
    """
    from datetime import timezone as _tz
    _ra = _retention_archive()
    d = archive_root() / table
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"{stamp}.jsonl.gz"
    sql = f"SELECT row_to_json(t) FROM {table} t WHERE t.{col} < now() - interval '{days} days'{guard}"
    if conn is not None:
        src = conn.cursor(name=f"db_retention_archive_{table}"[:63])
        src.itersize = 2000
    else:
        src = cur
    src.execute(sql)
    n, sha, nbytes = _ra.write_jsonl_gz(src, path)
    if src is not cur:
        src.close()
    if n == 0:
        path.unlink(missing_ok=True)
        return 0, str(path)
    # 2026-10-09: every archive carries a row count + sha256 manifest (RetentionArchiveManifest@v1);
    # 2026-10-11: plus a tripwire line (write_manifest) and a verified re-read before the DELETE.
    _ra.write_manifest(path, table=table, rows=n, sha256=sha, bytes=nbytes,
                       predicate=f"{col} < now() - interval '{days} days'")
    ok, why = _ra.verify_archive(path, expected_rows=n, expected_sha256=sha)
    if not ok:
        raise _ra.ArchiveVerifyError(f"{table}: archive re-read failed: {why} (archive {path}); delete refused")
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


_SQL_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_SOURCE_SPEC_KEYS = ("source_column", "source_key_column", "source_table", "source_table_key", "source_table_ts")


def _source_table_spec(r: dict, source: str) -> dict:
    """D10 (2026-10-21, operator: fix-first): a source window measures the SOURCE document's age, not the
    embedding's created_at. Measuring the embedding looped: archive, delete, then rag_indexer re-embeds the
    still-present source row (its NOT EXISTS check), archive, delete again. Every source value must name its
    table, key and timestamp in `source_windows_source_tables`; a missing or malformed entry is a config
    error (fail closed), never a fallback to the embedding's own age."""
    spec = (r.get("source_windows_source_tables") or {}).get(source)
    if not isinstance(spec, dict) or not r.get("source_key_column"):
        raise SystemExit(f"ERROR: registry row {r.get('table')} source_windows[{source}] needs "
                         f"source_windows_source_tables[{source}] {{table, key, ts_column}} and source_key_column "
                         "(D10: the window measures the source document's age)")
    out = {"source_key_column": r.get("source_key_column"), "source_table": spec.get("table"),
           "source_table_key": spec.get("key"), "source_table_ts": spec.get("ts_column")}
    for k, v in out.items():
        if not isinstance(v, str) or not _SQL_IDENT_RE.match(v):
            raise SystemExit(f"ERROR: registry row {r.get('table')} source_windows[{source}] {k}={v!r} "
                             "is not a plain SQL identifier")
    return out


def enforced_source_windows(doc: dict) -> list[dict]:
    out = []
    for r in doc["policies"]:
        sw = r.get("source_windows")
        if not sw or r.get("class") in ("KEEP_FOREVER", "EXTERNAL_POLICY"):
            continue
        # 2026-10-09 due-diligence audit F: social_post deletion is not operator-approved. Declared-but-off;
        # D10 (2026-10-21) fixed the predicate first (source-document age) and keeps enabling a separate
        # operator ruling. The junk purge stays manual.
        if r.get("source_windows_enabled") is False:
            continue
        if r.get("source_windows_class") != "ARCHIVE_THEN_DELETE" or not r.get("source_column"):
            raise SystemExit(f"ERROR: registry row {r.get('table')} source_windows needs source_column and "
                             "source_windows_class ARCHIVE_THEN_DELETE")
        for value, days in sorted(sw.items()):
            out.append({"table": r["table"], "ts_column": r["ts_column"], "source_column": r["source_column"],
                        "source": value, "days": int(days), **_source_table_spec(r, value),
                        "batch_rows": int(r.get("source_windows_batch_rows") or DEFAULT_SOURCE_BATCH_ROWS),
                        "max_rows": int(r.get("source_windows_max_rows_per_run") or DEFAULT_SOURCE_MAX_ROWS_PER_RUN)})
    return out


def source_window_predicate(w: dict, guard: str = "") -> tuple[str, tuple]:
    """Rows of `source` whose SOURCE document is older than the window (D10). The embedding's own
    created_at is not consulted. An embedding whose source row no longer exists is not selected here:
    it cannot be re-embedded, and the row's own age rail (window_days) owns it."""
    for k in _SOURCE_SPEC_KEYS:
        if not _SQL_IDENT_RE.match(str(w.get(k) or "")):
            raise ValueError(f"source window {w.get('table')}.{w.get('source')}: {k}={w.get(k)!r} is not a plain "
                             "SQL identifier (D10: windows measure the source document's age)")
    return (f't."{w["source_column"]}" = %s AND EXISTS (SELECT 1 FROM "{w["source_table"]}" s '
            f'WHERE s."{w["source_table_key"]}" = t."{w["source_key_column"]}" '
            f'AND s."{w["source_table_ts"]}" < now() - make_interval(days => %s)){guard}',
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
            basis = f"{w['source_table']}.{w['source_table_ts']}"  # D10: the age is the source document's
            if dry_run:
                cur.execute(f"SELECT count(*) FROM {w['table']} t WHERE {where}", params)
                n = cur.fetchone()[0]
                print(f"  {label:<43} {basis:<18} {w['days']:>5}  {n:>8}  (source window, archive-first;"
                      f" per-run cap {w['max_rows']:,})")
                total += min(n, w["max_rows"])
                continue
            res = ra.archive_then_delete_batches(
                conn, table=w["table"], where_sql=where, params=params,
                label=f"source_window_{w['source']}", archive_dir=archive_root() / w["table"],
                batch_rows=w["batch_rows"], max_rows=w["max_rows"])
            total += res["rows_deleted"]
            print(f"  {label:<43} {basis:<18} {w['days']:>5}  {res['rows_deleted']:>8}  (archived "
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


def _verify_db_write_grant() -> dict:
    """--apply authority (2026-10-11, overnight finding 4): the operator's db-write grant id from
    TRADEAI_DB_WRITE_GRANT, checked against the ACTIVE guard-ledger record (read-only peek)."""
    from pathlib import Path as _P
    _scripts = str(_P(__file__).resolve().parent)
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    from lib import db_write_grant
    return db_write_grant.verify(os.environ.get(db_write_grant.ENV))


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
        # Grant first: a refused run opens no connection and writes nothing. Dry run needs none.
        grant = _verify_db_write_grant()
        receipt["grant"] = grant
        if not grant.get("ok"):
            receipt.update(status="refused", reason=f"db-write grant: {grant.get('reason')}")
            print(_json.dumps(receipt, indent=1, default=str, sort_keys=True))
            return 2
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


# ── File prunes (2026-10-11, retention-all-managed) ──────────────────────────
# The four globs that used to be hard-coded here (and unlink()ed with no archive) are registry rows now:
# config/data_retention_policy.json ``file_prune`` (FilePrunePolicy). ``archive: true`` (all four) tars the
# selected files with a per-member sha256 manifest + tripwire under <state>/archive/file_prune/<id>/,
# re-reads the tar, and only then unlinks. ``archive: false`` keeps the inherited unlink (rollback lever).
LEGACY_FILE_PRUNE = [
    {"id": "raw_snapshots", "dir": "data/portfolios/state/raw_snapshots", "pattern": "*.json", "days": 14},
    {"id": "ticker_snapshot_history", "dir": "data/portfolios/state/ticker_snapshot_history", "pattern": "*.json",
     "days": 14},
    {"id": "ingestion_summaries", "dir": "data/logs", "pattern": "ingestion_summary_*.json", "days": 7},
    {"id": "catalyst_cache", "dir": "data", "pattern": "catalyst_cache_*.json", "days": 3},
]


def file_prune_policies(doc: dict) -> list[dict]:
    """Registry ``file_prune`` rows; the legacy list (archive off) only if the registry has none."""
    rows = doc.get("file_prune")
    if rows is None:
        return [{**r, "archive": False} for r in LEGACY_FILE_PRUNE]
    out = []
    for r in rows:
        if not r.get("id") or not r.get("dir") or not r.get("pattern") or not isinstance(r.get("days"), int):
            raise SystemExit(f"ERROR: file_prune row {r!r} needs id, dir, pattern and int days")
        out.append(r)
    return out


def select_old_files(directory: "pathlib.Path", pattern: str, days: int, now: float | None = None) -> list:
    import time
    cutoff = (now if now is not None else time.time()) - days * 86400
    return sorted(f for f in directory.glob(pattern) if f.is_file() and f.stat().st_mtime < cutoff)


def run_file_prunes(policies: list[dict], project: "pathlib.Path", dry_run: bool,
                    now: float | None = None) -> tuple[int, list[str]]:
    """Returns (files pruned or would-prune, failed ids). A failed archive unlinks nothing."""
    ra = _retention_archive()
    print(f"\n{'DRY RUN — ' if dry_run else ''}File Pruning")
    print(f"{'Directory':<55} {'Pattern':<25} {'Days':>5}  {'Pruned' if not dry_run else 'Would':>8}  Action")
    print("-" * 98)
    total, failed = 0, []
    for r in policies:
        directory = project / r["dir"]
        if not directory.is_dir():
            continue
        old = select_old_files(directory, r["pattern"], int(r["days"]), now=now)
        if not old:
            continue
        archive = r.get("archive") is True
        action = "ARCHIVE+UNLINK" if archive else "UNLINK (no archive)"
        if not dry_run:
            try:
                if archive:
                    res = ra.archive_files_then_unlink(old, base_dir=directory, archive_dir=ra.file_archive_root() / r["id"],
                                                       label=r["id"])
                    action += f" -> {pathlib.Path(res['archive']).name} ({res['bytes']:,} B)"
                else:
                    for f in old:
                        f.unlink()
            except Exception as e:  # noqa: BLE001 -- one prune failing must not hide the others
                failed.append(f"file_prune:{r['id']}")
                print(f"  ERROR: file_prune {r['id']}: {e}")
                continue
        total += len(old)
        print(f"  {str(directory):<53} {r['pattern']:<25} {int(r['days']):>5}  {len(old):>8}  {action}")
    print("-" * 98)
    print(f"  Total {'would prune' if dry_run else 'pruned'}: {total:,} files")
    return total, failed


# ── Archive-growth projection (2026-10-11, read-only) ────────────────────────
# Per enforced row: rows the next run would remove (tonight), rows/day crossing the window (the week
# just past the boundary) and rows/day arriving (last 7 d), and compressed archive bytes/row from a
# gzip of a sample of the rows it would archive -> GB/month if the row archives first. The registry's
# ``archive_growth_cap_gb_month`` is the operator's budget for all archive-first rows together.
DEFAULT_ARCHIVE_CAP_GB_MONTH = 2.0


def project_row(cur, table: str, col: str, days: int, archive_first: bool, sample_rows: int = 200) -> dict:
    ra = _retention_archive()
    out = {"table": table, "ts_column": col, "window_days": days, "archive_first": archive_first}
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s "
                "AND column_name=%s", (table, col))
    if not cur.fetchone():
        out["status"] = "absent"
        return out
    guard = fk_guard(cur, table)
    cur.execute(f"SELECT count(*) FROM {table} t WHERE t.{col} < now() - make_interval(days => %s){guard}", (days,))
    out["tonight_rows"] = int(cur.fetchone()[0])
    cur.execute(f"SELECT count(*) FROM {table} t WHERE t.{col} >= now() - make_interval(days => %s) "
                f"AND t.{col} < now() - make_interval(days => %s)", (days + 7, days))
    out["boundary_rows_per_day"] = round(int(cur.fetchone()[0]) / 7.0, 1)
    cur.execute(f"SELECT count(*) FROM {table} t WHERE t.{col} >= now() - interval '7 days'")
    out["inflow_rows_per_day"] = round(int(cur.fetchone()[0]) / 7.0, 1)
    cur.execute(f"SELECT row_to_json(t) FROM {table} t WHERE t.{col} < now() - make_interval(days => %s) LIMIT %s",
                (days, int(sample_rows)))
    sample = cur.fetchall()
    out["sample_basis"] = "eligible"
    if not sample:
        cur.execute(f"SELECT row_to_json(t) FROM {table} t ORDER BY t.{col} DESC NULLS LAST LIMIT %s", (int(sample_rows),))
        sample = cur.fetchall()
        out["sample_basis"] = "newest"
    bpr = ra.gz_bytes_per_row(sample)
    out["sample_rows"] = len(sample)
    out["gz_bytes_per_row"] = round(bpr, 1) if bpr is not None else None
    rate = max(out["boundary_rows_per_day"], out["inflow_rows_per_day"])
    out["rows_per_day"] = rate
    out["gb_per_month"] = round(rate * 30.0 * (bpr or 0.0) / 1e9, 4)
    out["tonight_archive_gb"] = round(out["tonight_rows"] * (bpr or 0.0) / 1e9, 4)
    out["status"] = "ok"
    return out


def archive_projection(conn, registry: dict, sample_rows: int = 200, tables: list[str] | None = None) -> dict:
    """Read-only. The caller opens the session read-only; this only SELECTs."""
    cur = conn.cursor()
    rows, errors = [], []
    for table, col, days, archive_first in enforced_policies(registry):
        if tables and table not in tables:
            continue
        try:
            rows.append(project_row(cur, table, col, days, archive_first, sample_rows))
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            errors.append({"table": table, "error": f"{type(e).__name__}: {e}"[:200]})
    cur.close()
    cap = float(registry.get("archive_growth_cap_gb_month") or DEFAULT_ARCHIVE_CAP_GB_MONTH)
    ok = [r for r in rows if r.get("status") == "ok"]
    archiving = [r for r in ok if r["archive_first"]]
    hard = [r for r in ok if not r["archive_first"]]
    total_af = round(sum(r["gb_per_month"] for r in archiving), 4)
    return {"schema": "RetentionArchiveProjection@v1", "as_of": datetime.now().astimezone().isoformat(),
            "cap_gb_month": cap, "rows": rows, "errors": errors,
            "archive_first_gb_month": total_af, "hard_delete_gb_month_if_archived": round(sum(r["gb_per_month"] for r in hard), 4),
            "within_cap": total_af <= cap,
            "over_cap_rows": sorted([r["table"] for r in archiving if r["gb_per_month"] > cap])}


def run_projection(as_json: bool = False, sample_rows: int = 200, tables: list[str] | None = None) -> int:
    import json as _json
    conn = _connect()
    conn.set_session(readonly=True)
    try:
        conn.cursor().execute("SET statement_timeout = '120s'")
        rep = archive_projection(conn, load_registry(), sample_rows=sample_rows, tables=tables)
    finally:
        conn.rollback()
        conn.close()
    if as_json:
        print(_json.dumps(rep, indent=1, default=str))
        return 0 if rep["within_cap"] and not rep["errors"] else 1
    print(f"ARCHIVE PROJECTION (read-only) — cap {rep['cap_gb_month']} GB/month")
    print(f"{'Table':<45} {'af':>3} {'days':>5} {'tonight':>9} {'rows/d':>9} {'gzB/row':>8} {'GB/mo':>8}")
    for r in sorted(rep["rows"], key=lambda r: -(r.get("gb_per_month") or 0)):
        if r.get("status") != "ok":
            continue
        print(f"  {r['table']:<43} {'Y' if r['archive_first'] else '-':>3} {r['window_days']:>5} {r['tonight_rows']:>9} "
              f"{r['rows_per_day']:>9} {r['gz_bytes_per_row'] or 0:>8.0f} {r['gb_per_month']:>8.4f}")
    print(f"  archive-first total {rep['archive_first_gb_month']} GB/month (cap {rep['cap_gb_month']}); "
          f"hard-delete rows if archived: {rep['hard_delete_gb_month_if_archived']} GB/month; errors {len(rep['errors'])}")
    return 0 if rep["within_cap"] and not rep["errors"] else 1


def run(dry_run: bool = False):
    blocked = _disk_too_low_for_retention()
    if blocked and not dry_run:
        print(f"SKIP retention — disk below critical floor: {blocked}")
        print("Free space first, then re-run. Refusing DELETEs that need WAL under ENOSPC.")
        return {"ok": False, "skipped": True, "reason": blocked, "deleted": 0}

    conn = _connect()
    if dry_run:
        # 2026-10-11: a dry run must not be able to REACH a mutation (AGENTS.md §6) -- the session itself
        # refuses writes, so a code path that forgot to check dry_run fails instead of deleting.
        conn.set_session(readonly=True)
    cur = conn.cursor()
    total_deleted = 0
    failures: list[str] = []

    print(f"{'DRY RUN — ' if dry_run else ''}DB Retention Policy — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'Table':<45} {'Column':<18} {'Days':>5}  {'Deleted' if not dry_run else 'Would':>8}  Action")
    print("-" * 98)

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
                n_arch = None
                if archive_first and matching > 0:
                    n_arch, path = archive_rows(cur, table, col, days, guard, conn=conn)
                    if n_arch != matching:
                        raise RuntimeError(f"archived {n_arch} != matching {matching}; delete refused (archive {path})")
                cur.execute(f"DELETE FROM {table} t WHERE t.{col} < now() - interval '{days} days'{guard}")
                count = cur.rowcount
                if n_arch is not None and count != n_arch:
                    # 2026-10-11: a row that matched between the archive SELECT and the DELETE would be
                    # deleted unarchived. Roll back; the next night archives the whole set again.
                    raise RuntimeError(f"deleted {count} != archived {n_arch}; rolled back (archive {path} kept)")
                conn.commit()
                if n_arch:
                    archived_total += n_arch

            if count > 0:
                total_deleted += count
                if dry_run and archive_first:
                    archived_total += count
                action = "ARCHIVE+DELETE" if archive_first else "DELETE (no archive)"
                print(f"  {table:<43} {col:<18} {days:>5}  {count:>8}  {action}")
        except Exception as e:
            conn.rollback()
            failures.append(table)
            print(f"  ERROR: {table}: {e}")

    sw_total, sw_failed = run_source_windows(cur, conn, enforced_source_windows(registry), dry_run)
    total_deleted += sw_total
    failures.extend(sw_failed)

    print("-" * 98)
    # The "Total …: N rows; archived first: M" shape is parsed (report_lane_governance_packet._RET_TOTAL,
    # weekly_disk_cleanup_notify); a dry run archives nothing, so it reports 0 there and the plan after it.
    print(f"  Total {'would delete' if dry_run else 'deleted'}: {total_deleted:,} rows; "
          f"archived first: {0 if dry_run else archived_total:,}"
          f" (+{sw_total:,} source-window rows, archive-first)"
          + (f"; would archive first: {archived_total:,}" if dry_run else ""))
    unarchived = [t for t, _c, _d, af in enforced if not af]
    print(f"  rows with archive_first: {sum(1 for *_x, af in enforced if af)} of {len(enforced)};"
          f" hard DELETE (no archive): {len(unarchived)}")
    cur.close()
    conn.close()

    # ── File pruning (registry ``file_prune``; 2026-10-11 archive-then-unlink) ─────────────────
    import pathlib
    project = pathlib.Path(os.getenv("PROJECT_ROOT", "."))
    _p_total, p_failed = run_file_prunes(file_prune_policies(registry), project, dry_run)
    failures.extend(p_failed)

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
    parser.add_argument("--apply", action="store_true",
                        help="with --junk-fused-signal-embeddings: archive, verify, delete. Requires "
                             "TRADEAI_DB_WRITE_GRANT=<active db-write grant id>; recorded in the receipt")
    parser.add_argument("--batch-rows", type=int, default=DEFAULT_SOURCE_BATCH_ROWS)
    parser.add_argument("--max-rows", type=int, default=200000, help="per-run cap for the one-time mode")
    parser.add_argument("--archive-projection", action="store_true",
                        help="READ-ONLY: per registry row, rows tonight, rows/day, gzip bytes/row and archive GB/month "
                             "against archive_growth_cap_gb_month. Nothing else runs.")
    parser.add_argument("--json", action="store_true", help="with --archive-projection: JSON report")
    parser.add_argument("--table", action="append", help="with --archive-projection: limit to these tables")
    args = parser.parse_args()
    if args.archive_projection:
        raise SystemExit(run_projection(as_json=args.json, tables=args.table))
    if args.junk_fused_signal_embeddings:
        raise SystemExit(purge_junk_fused_embeddings(apply=args.apply and not args.dry_run,
                                                     batch_rows=args.batch_rows, max_rows=args.max_rows))
    if args.apply:
        raise SystemExit("ERROR: --apply is only for --junk-fused-signal-embeddings (the nightly run applies by default)")
    raise SystemExit(run(dry_run=args.dry_run))
