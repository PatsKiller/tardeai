-- Options pipeline Stage B: paper-outcome ledger for paper-only options strategies
-- (deep_itm_call first). Additive + idempotent — no existing table is touched.
--
-- Feeds scripts/lib/options_pipeline/validation.py:
--   record_outcome()      → one row per closed paper proposal (upsert on proposal_id)
--   validation_status()   → n/30 · profit factor · win rate vs config validation_gate
-- ADVISORY ONLY: nothing here (or in the validation module) enables live execution.
-- live_allowed stays false in config/strategies/deep_itm_call.yaml; a met gate is
-- reported as "operator decision required", never acted on.

CREATE TABLE IF NOT EXISTS options_paper_outcomes (
    id            BIGSERIAL PRIMARY KEY,
    proposal_id   TEXT NOT NULL UNIQUE,      -- options_approval_queue.proposal_id lineage
    strategy_id   TEXT NOT NULL DEFAULT 'deep_itm_call',
    symbol        TEXT,
    opened_at     TIMESTAMPTZ,
    closed_at     TIMESTAMPTZ,
    entry_debit   NUMERIC,                   -- total premium paid ($, per position)
    exit_value    NUMERIC,                   -- closing value ($)
    pnl           NUMERIC,                   -- realized P/L ($)
    pnl_r         NUMERIC,                   -- realized R multiple vs planned risk
    outcome       TEXT NOT NULL,             -- win | loss | scratch
    exit_reason   TEXT,                      -- thesis_break | delta_decay | dte_21_roll | expiry | manual
    notes         TEXT,
    meta          JSONB DEFAULT '{}'::jsonb, -- discovery_ref, dte bucket, entry snapshot, ...
    recorded_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_opo_strategy_closed
    ON options_paper_outcomes (strategy_id, closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_opo_symbol
    ON options_paper_outcomes (symbol, recorded_at DESC);
