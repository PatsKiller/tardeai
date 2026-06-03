#!/usr/bin/env python3
"""Backtest result-history archiver — APPEND-ONLY.

Snapshots one permanent aggregate row per backtest run into
backtest_result_history. Never UPDATEs or DELETEs existing rows
(ON CONFLICT (run_id) DO NOTHING), so the historical record of
"how well we could have done" is preserved run-over-run.

Run from cron right after each backtester job, e.g.:
  0 6 * * 1-5 ... strategy_backtester.py ... && $PY scripts/backtest_history_snapshot.py
"""
import os
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines():
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


def main():
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute(SNAPSHOT)
    log.info("appended %d new run snapshot(s)", cur.rowcount)
    cur.execute("SELECT COUNT(*) FROM backtest_result_history")
    log.info("history total rows: %d", cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
