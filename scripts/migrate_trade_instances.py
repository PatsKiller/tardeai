#!/usr/bin/env python3
"""migrate_trade_instances.py — canonical broker/account-neutral trade lifecycle (additive, idempotent).

Creates `trade_instances` (canonical), `trade_edge_comparison` (canonical edge), and adds
`trade_instance_id` to the closed-loop consumer tables. paper_trade_id / related_trade_id stay as
legacy-compat. No data mutation, no trading behaviour.
"""
import os, psycopg2

TRADE_INSTANCES = """
CREATE TABLE IF NOT EXISTS trade_instances (
  id BIGSERIAL PRIMARY KEY,
  trade_uid TEXT UNIQUE NOT NULL,
  source_system TEXT NOT NULL,
  source_table TEXT NOT NULL,
  source_trade_id TEXT NOT NULL,
  execution_broker TEXT,
  execution_account TEXT,
  execution_environment TEXT,
  trade_mode TEXT,
  symbol TEXT NOT NULL,
  strategy_id TEXT,
  signal_id TEXT,
  source_signal_id TEXT,
  strategy_card_id TEXT,
  candidate_id TEXT,
  proposal_id TEXT,
  status TEXT,
  side TEXT,
  shares NUMERIC,
  entry_price NUMERIC,
  entry_time TIMESTAMPTZ,
  exit_price NUMERIC,
  exit_time TIMESTAMPTZ,
  pnl NUMERIC,
  pnl_pct NUMERIC,
  r_multiple NUMERIC,
  hold_time_min NUMERIC,
  trade_key TEXT,
  lineage_confidence TEXT,
  lineage_source TEXT,
  lineage_notes JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(source_table, source_trade_id)
);
CREATE INDEX IF NOT EXISTS idx_ti_symbol ON trade_instances(symbol);
CREATE INDEX IF NOT EXISTS idx_ti_source_system ON trade_instances(source_system);
CREATE INDEX IF NOT EXISTS idx_ti_status ON trade_instances(status);
"""

TRADE_EDGE = """
CREATE TABLE IF NOT EXISTS trade_edge_comparison (
  id BIGSERIAL PRIMARY KEY,
  trade_instance_id BIGINT REFERENCES trade_instances(id),
  source_trade_table TEXT,
  source_trade_id TEXT,
  proposal_snapshot_id BIGINT,
  trade_backtest_result_id BIGINT,
  expected_edge_source TEXT,
  expected_avg_r NUMERIC,
  expected_win_rate NUMERIC,
  realized_r NUMERIC,
  realized_pnl_pct NUMERIC,
  edge_delta_r NUMERIC,
  edge_assessment TEXT,
  backtest_assessment TEXT,
  comparison_source TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(trade_instance_id)
);
"""

# consumer tables that get an additive canonical link
CONSUMERS = ["hermes_research_intelligence", "journal_trade_reviews", "trade_backtest_results",
             "paper_trade_edge_comparison", "candidate_shadow_efficacy", "candidate_shadow_scores",
             "proposal_outcome_chain"]


def main():
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor()
    cur.execute(TRADE_INSTANCES)
    cur.execute(TRADE_EDGE)
    for t in CONSUMERS:
        cur.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS trade_instance_id BIGINT")
    c.commit()
    cur.execute("select count(*) from information_schema.columns where table_name='trade_instances'")
    print(f"trade_instances columns: {cur.fetchone()[0]}")
    for t in CONSUMERS:
        cur.execute("select count(*) from information_schema.columns where table_name=%s and column_name='trade_instance_id'", (t,))
        print(f"  {t}.trade_instance_id: {'OK' if cur.fetchone()[0] else 'MISSING'}")
    c.close()


if __name__ == "__main__":
    main()
