#!/usr/bin/env python3
"""Backtest result-history archiver — APPEND-ONLY.

Snapshots one permanent aggregate row per backtest run into
backtest_result_history. Never UPDATEs or DELETEs existing rows
(ON CONFLICT (run_id) DO NOTHING), so the historical record of
"how well we could have done" is preserved run-over-run.

Run from cron right after each backtester job, e.g.:
  0 6 * * 1-5 ... strategy_backtester.py ... && $PY scripts/backtest_history_snapshot.py

Refactor wave 2 (cron -> n8n, 2026-10-10; cron:L363):
- ``--dry-run`` opens a READ ONLY session, runs no DDL and no INSERT: it counts the runs the snapshot
  WOULD append (the same WHERE as SNAPSHOT, as a SELECT) and exits. No receipt.
- A real run writes data/runtime/backtest_history_snapshot_last.json (LaneRunReceipt@v1, ok_at only
  on success); a DB error still exits non-zero.
"""
import argparse
import json
import os
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV = ROOT / ".env"
for line in (_ENV.read_text().splitlines() if _ENV.exists() else []):  # absent in CI / a bare checkout
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backtest_history_snapshot")

DB = dict(host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "5432")),
          dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
          password=os.getenv("DB_PASSWORD", ""))

DDL = """
CREATE TABLE IF NOT EXISTS backtest_result_history (
  id SERIAL PRIMARY KEY,
  snapshot_at  TIMESTAMPTZ NOT NULL,
  run_id       TEXT UNIQUE,
  run_type     TEXT,
  trades       INT,
  wins         INT,
  win_rate     NUMERIC,
  total_pnl    NUMERIC,
  avg_r_multiple NUMERIC,
  expectancy_r NUMERIC,
  source       TEXT DEFAULT 'archiver',
  created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_brh_snapshot ON backtest_result_history(snapshot_at);
"""

# Append a permanent snapshot for every run that has trades but no history row yet.
SNAPSHOT = """
INSERT INTO backtest_result_history
  (snapshot_at, run_id, run_type, trades, wins, win_rate, total_pnl, avg_r_multiple, expectancy_r, source)
SELECT r.created_at, r.run_id, r.run_type,
       COUNT(*),
       COUNT(*) FILTER (WHERE sbt.pnl > 0),
       ROUND(100.0 * COUNT(*) FILTER (WHERE sbt.pnl > 0) / NULLIF(COUNT(*), 0), 1),
       ROUND(SUM(sbt.pnl)::numeric, 2),
       ROUND(AVG(sbt.r_multiple)::numeric, 3),
       ROUND(AVG(sbt.r_multiple)::numeric, 3),
       'archiver'
FROM strategy_backtest_trades sbt
JOIN strategy_backtest_runs r ON r.run_id = sbt.run_id
WHERE r.run_id NOT IN (SELECT run_id FROM backtest_result_history WHERE run_id IS NOT NULL)
GROUP BY r.run_id, r.run_type, r.created_at
ON CONFLICT (run_id) DO NOTHING;
"""

# Dry run: the SNAPSHOT's own selection, counted. Read-only; a missing history table means every run is new.
PREVIEW = """
SELECT COUNT(*) FROM (
  SELECT r.run_id
  FROM strategy_backtest_trades sbt
  JOIN strategy_backtest_runs r ON r.run_id = sbt.run_id
  WHERE r.run_id NOT IN (SELECT run_id FROM backtest_result_history WHERE run_id IS NOT NULL)
  GROUP BY r.run_id, r.run_type, r.created_at
) AS pending
"""
PREVIEW_NO_TABLE = """
SELECT COUNT(DISTINCT r.run_id)
FROM strategy_backtest_trades sbt JOIN strategy_backtest_runs r ON r.run_id = sbt.run_id
"""


def preview(conn) -> dict:
    """READ ONLY: what a real run would append. Never executes DDL or SNAPSHOT."""
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('public.backtest_result_history') IS NOT NULL")
    has_table = bool(cur.fetchone()[0])
    cur.execute(PREVIEW if has_table else PREVIEW_NO_TABLE)
    would = int(cur.fetchone()[0])
    total = None
    if has_table:
        cur.execute("SELECT COUNT(*) FROM backtest_result_history")
        total = int(cur.fetchone()[0])
    return {"mode": "dry_run", "history_table_exists": has_table, "history_rows": total,
            "would_write": {"table": "backtest_result_history", "rows": would},
            "would_run_ddl": not has_table}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Append-only backtest result-history snapshot")
    ap.add_argument("--dry-run", action="store_true", help="read-only: count what would be appended")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.lane_last_receipt import enforce_readonly, now_iso, write_receipt

    if args.dry_run:
        conn = psycopg2.connect(**DB)
        try:
            enforce_readonly(conn)  # the server refuses any write (AGENTS.md §6)
            out = preview(conn)
            conn.rollback()
        finally:
            conn.close()
        print(json.dumps(out, indent=2))
        return 0

    started_at = now_iso()
    try:
        conn = psycopg2.connect(**DB)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(DDL)
        cur.execute(SNAPSHOT)
        appended = cur.rowcount
        log.info("appended %d new run snapshot(s)", appended)
        cur.execute("SELECT COUNT(*) FROM backtest_result_history")
        total = cur.fetchone()[0]
        log.info("history total rows: %d", total)
        conn.close()
    except Exception as exc:
        write_receipt("backtest_history_snapshot", ok=False, started_at=started_at,
                      error=f"{type(exc).__name__}: {exc}")
        raise
    write_receipt("backtest_history_snapshot", ok=True, started_at=started_at,
                  summary={"appended": appended, "history_rows": total})
    return 0


if __name__ == "__main__":
    sys.exit(main())
