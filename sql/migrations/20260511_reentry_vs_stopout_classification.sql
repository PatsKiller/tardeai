-- Migration: Re-entry vs Stop-out Classification
-- Date: 2026-05-11
-- Purpose: Distinguish true stop-outs from relisted/market-reconnection events
--          in the learning cycle. Prevents the model from penalizing normal
--          market behavior (relisting) as failed recommendations.

-- ── 1. New classification columns on stopped_out_watch ──────────────────

ALTER TABLE stopped_out_watch
  ADD COLUMN IF NOT EXISTS explicit_stop_out       boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS relisted_without_stop_out boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS market_reconnection_event boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS exit_type                text DEFAULT 'unclassified',
  ADD COLUMN IF NOT EXISTS patience_score           numeric(4,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS relist_count             integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS first_seen_at            timestamp with time zone,
  ADD COLUMN IF NOT EXISTS last_relist_at           timestamp with time zone;

-- exit_type constraint: explicit categories
ALTER TABLE stopped_out_watch
  DROP CONSTRAINT IF EXISTS stopped_out_watch_exit_type_check;
ALTER TABLE stopped_out_watch
  ADD CONSTRAINT stopped_out_watch_exit_type_check
  CHECK (exit_type IN ('true_stop_out', 'relist_no_exit', 'market_reconnection', 'unclassified'));

-- ── 2. Update analyst_verdict constraint to allow market_relist_monitor ──

ALTER TABLE stopped_out_watch
  DROP CONSTRAINT IF EXISTS stopped_out_watch_analyst_verdict_check;
ALTER TABLE stopped_out_watch
  ADD CONSTRAINT stopped_out_watch_analyst_verdict_check
  CHECK (analyst_verdict IN (
    'reentry_candidate',
    'wait_monitor',
    'do_not_reenter',
    'market_relist_monitor'   -- new: relisted without stop-out, patience mode
  ));

-- ── 3. Index for filtering by exit type ─────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_sow_exit_type
  ON stopped_out_watch (exit_type)
  WHERE is_active = true;

-- ── 4. Relist event log — tracks each relist occurrence ─────────────────

CREATE TABLE IF NOT EXISTS stopped_out_relist_events (
  id              serial PRIMARY KEY,
  watch_id        integer NOT NULL REFERENCES stopped_out_watch(id),
  symbol          text NOT NULL,
  account         text,
  relist_date     date NOT NULL DEFAULT CURRENT_DATE,
  price_at_relist numeric,
  price_at_delist numeric,
  days_delisted   integer,
  relist_reason   text,          -- 'auction_cycle', 'seller_relist', 'lienholder_change', 'unknown'
  classified_as   text NOT NULL DEFAULT 'market_reconnection',
  evidence        jsonb DEFAULT '{}',
  created_at      timestamp with time zone DEFAULT now(),
  UNIQUE (watch_id, relist_date)
);

CREATE INDEX IF NOT EXISTS idx_relist_symbol ON stopped_out_relist_events (symbol);
CREATE INDEX IF NOT EXISTS idx_relist_watch  ON stopped_out_relist_events (watch_id);

-- ── 5. Backfill: mark all existing records as unclassified ──────────────

UPDATE stopped_out_watch
   SET exit_type = 'unclassified',
       explicit_stop_out = false,
       relisted_without_stop_out = false,
       market_reconnection_event = false
 WHERE exit_type IS NULL OR exit_type = 'unclassified';

-- ── 6. Performance view: exclude relists from failure metrics ───────────

CREATE OR REPLACE VIEW v_true_stopout_performance AS
SELECT
  sow.symbol,
  sow.account,
  sow.analyst_verdict,
  sow.analyst_confidence,
  sow.exit_price,
  sow.stop_price,
  sow.exit_type,
  sow.explicit_stop_out,
  sow.relisted_without_stop_out,
  sow.patience_score,
  sow.relist_count,
  sow.stopped_out_at,
  sow.created_at
FROM stopped_out_watch sow
WHERE sow.exit_type = 'true_stop_out'
  AND sow.explicit_stop_out = true;

-- View: relisted items (not failures)
CREATE OR REPLACE VIEW v_relist_patience_tracking AS
SELECT
  sow.symbol,
  sow.account,
  sow.analyst_verdict,
  sow.patience_score,
  sow.relist_count,
  sow.first_seen_at,
  sow.last_relist_at,
  sow.analyst_confidence,
  sow.exit_type,
  re.relist_date AS last_relist_event_date,
  re.price_at_relist,
  re.relist_reason
FROM stopped_out_watch sow
LEFT JOIN LATERAL (
  SELECT relist_date, price_at_relist, relist_reason
  FROM stopped_out_relist_events
  WHERE watch_id = sow.id
  ORDER BY relist_date DESC LIMIT 1
) re ON true
WHERE sow.relisted_without_stop_out = true
  AND sow.is_active = true;
