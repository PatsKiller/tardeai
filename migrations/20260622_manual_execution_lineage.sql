-- manual_execution_lineage — closed-loop tracking for manual broker executions
-- Links watchlist / watchpool / proposal / options ideas → manual execution → journal / learning

CREATE TABLE IF NOT EXISTS manual_execution_log (
  id                BIGSERIAL PRIMARY KEY,
  symbol            TEXT NOT NULL,
  account           TEXT,
  broker            TEXT,
  execution_type    TEXT NOT NULL DEFAULT 'equity',  -- equity | option
  origin_type       TEXT,                           -- watchlist | watchpool | proposal | options_proposal | directive | manual
  origin_id         TEXT,
  origin_confidence TEXT NOT NULL DEFAULT 'inferred', -- exact | inferred | manual
  proposal_id       BIGINT,
  options_proposal_id TEXT,
  strategy_id       TEXT,
  shares            INT,
  contracts         INT,
  entry_price       NUMERIC,
  stop_price        NUMERIC,
  target_price      NUMERIC,
  strike            NUMERIC,
  expiration        DATE,
  option_side       TEXT,
  risk_reward       NUMERIC,
  outcome           TEXT NOT NULL DEFAULT 'pending',  -- pending | open | win | loss | breakeven
  outcome_pnl       NUMERIC,
  outcome_pnl_pct   NUMERIC,
  adjusted_params   JSONB NOT NULL DEFAULT '{}',
  notes             TEXT,
  journaled         BOOLEAN NOT NULL DEFAULT FALSE,
  learning_synced   BOOLEAN NOT NULL DEFAULT FALSE,
  executed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_at         TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mel_symbol ON manual_execution_log(symbol);
CREATE INDEX IF NOT EXISTS idx_mel_account ON manual_execution_log(account);
CREATE INDEX IF NOT EXISTS idx_mel_origin ON manual_execution_log(origin_type, origin_id);
CREATE INDEX IF NOT EXISTS idx_mel_outcome ON manual_execution_log(outcome);
CREATE INDEX IF NOT EXISTS idx_mel_executed_at ON manual_execution_log(executed_at DESC);