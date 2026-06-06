#!/usr/bin/env python3
"""migrate_paper_trades_lineage.py — Step 1 additive lineage columns on paper_trades (idempotent)."""
import os, psycopg2
c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                     user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"]); cur = c.cursor()
cur.execute("""ALTER TABLE paper_trades
  ADD COLUMN IF NOT EXISTS signal_id TEXT,
  ADD COLUMN IF NOT EXISTS source_signal_id TEXT,
  ADD COLUMN IF NOT EXISTS source_strategy_card_id TEXT,
  ADD COLUMN IF NOT EXISTS strategy_card_id TEXT,
  ADD COLUMN IF NOT EXISTS candidate_id TEXT,
  ADD COLUMN IF NOT EXISTS source_proposal_id TEXT,
  ADD COLUMN IF NOT EXISTS execution_account TEXT,
  ADD COLUMN IF NOT EXISTS execution_broker TEXT,
  ADD COLUMN IF NOT EXISTS execution_environment TEXT,
  ADD COLUMN IF NOT EXISTS lineage_source TEXT,
  ADD COLUMN IF NOT EXISTS lineage_stamped_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS lineage_confidence TEXT,
  ADD COLUMN IF NOT EXISTS lineage_notes JSONB DEFAULT '{}'::jsonb""")
c.commit(); print("paper_trades lineage columns ensured (additive, idempotent)"); c.close()
