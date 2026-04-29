-- 011_decision_safety.sql — Phase 14: Synthesis Safety Engine
BEGIN;

ALTER TABLE watchlist_final_synthesis
    ADD COLUMN IF NOT EXISTS decision_safety TEXT DEFAULT 'pending'
        CHECK (decision_safety IN ('safe','unsafe','blocked','pending')),
    ADD COLUMN IF NOT EXISTS safety_reasons JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS portfolio_context_used BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS income_context_used BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS target_allocation_used BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS safety_overrides JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS superseded BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS superseded_by TEXT,
    ADD COLUMN IF NOT EXISTS synthesis_version INTEGER DEFAULT 1;

CREATE TABLE IF NOT EXISTS watchlist_synthesis_safety_history (
    id                      BIGSERIAL PRIMARY KEY,
    symbol                  TEXT NOT NULL,
    synthesis_version       INTEGER,
    decision_safety         TEXT,
    recommendation_before   TEXT,
    recommendation_after    TEXT,
    safety_reasons          JSONB DEFAULT '[]',
    overrides_applied       JSONB DEFAULT '{}',
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_safety_hist_symbol ON watchlist_synthesis_safety_history (symbol, created_at DESC);

COMMIT;
