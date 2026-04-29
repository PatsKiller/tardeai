-- 006_analysis_maturity.sql — Phase 11: Analysis Maturity, Full Narratives, Escalation Policy
-- Run: psql -d trade_ai -f linux_port_v2/linux/migrations/006_analysis_maturity.sql

BEGIN;

-- 1. Analysis maturity tracking per symbol
CREATE TABLE IF NOT EXISTS watchlist_analysis_maturity (
    symbol              TEXT PRIMARY KEY,
    analysis_stage      TEXT NOT NULL DEFAULT 'raw_data_only'
        CHECK (analysis_stage IN (
            'raw_data_only',
            'strategy_card_ready',
            'routed',
            'specialist_review_partial',
            'specialist_review_complete',
            'full_chain_complete',
            'final_synthesis_complete',
            'needs_iteration',
            'failed'
        )),
    raw_data_ready      BOOLEAN NOT NULL DEFAULT FALSE,
    strategy_card_ready BOOLEAN NOT NULL DEFAULT FALSE,
    maria_status        TEXT NOT NULL DEFAULT 'not_required'
        CHECK (maria_status IN ('not_required', 'required', 'queued', 'processing', 'completed', 'failed')),
    steph_status        TEXT NOT NULL DEFAULT 'not_required'
        CHECK (steph_status IN ('not_required', 'required', 'queued', 'processing', 'completed', 'failed')),
    risk_status         TEXT NOT NULL DEFAULT 'not_required'
        CHECK (risk_status IN ('not_required', 'required', 'queued', 'processing', 'completed', 'failed')),
    tax_status          TEXT NOT NULL DEFAULT 'not_required'
        CHECK (tax_status IN ('not_required', 'required', 'queued', 'processing', 'completed', 'failed')),
    full_chain_status   TEXT NOT NULL DEFAULT 'not_required'
        CHECK (full_chain_status IN ('not_required', 'required', 'queued', 'processing', 'completed', 'failed')),
    final_synthesis_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (final_synthesis_status IN ('pending', 'queued', 'processing', 'completed', 'failed')),
    escalation_policy   TEXT,            -- strategy_type that determined required agents
    required_agents     TEXT[],          -- e.g. {'maria','steph','risk'}
    completed_agents    TEXT[],          -- e.g. {'maria'}
    missing_agents      TEXT[],          -- computed: required - completed
    last_completed_agent TEXT,
    last_completed_at   TIMESTAMPTZ,
    needs_iteration     BOOLEAN NOT NULL DEFAULT TRUE,
    iteration_reason    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Expand watchlist_agent_results with full narrative fields
ALTER TABLE watchlist_agent_results
    ADD COLUMN IF NOT EXISTS full_narrative  TEXT,
    ADD COLUMN IF NOT EXISTS reason_codes    TEXT[],
    ADD COLUMN IF NOT EXISTS model_used      TEXT,
    ADD COLUMN IF NOT EXISTS prompt_hash     TEXT,
    ADD COLUMN IF NOT EXISTS input_data_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS raw_response    TEXT,
    ADD COLUMN IF NOT EXISTS started_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at    TIMESTAMPTZ;

-- 3. Final synthesis table
CREATE TABLE IF NOT EXISTS watchlist_final_synthesis (
    symbol              TEXT PRIMARY KEY,
    recommendation      TEXT NOT NULL,
    confidence          NUMERIC,
    action              TEXT,           -- 'buy', 'hold', 'sell', 'add', 'trim', 'avoid'
    reason_codes        TEXT[],
    conflicts           TEXT[],         -- disagreements between analysts
    unresolved          TEXT[],         -- what is still missing
    next_review_date    DATE,
    synthesis_narrative TEXT,
    input_agents        TEXT[],         -- which agent results fed this
    model_used          TEXT,
    raw_response        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Escalation policy reference table
CREATE TABLE IF NOT EXISTS watchlist_escalation_policies (
    strategy_type       TEXT PRIMARY KEY,
    required_agents     TEXT[] NOT NULL,
    optional_agents     TEXT[],
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed escalation policies
INSERT INTO watchlist_escalation_policies (strategy_type, required_agents, optional_agents, description) VALUES
    ('income',              '{steph,risk}',           '{maria}',       'Income/dividend ETF: Steph allocation + Risk technical required, Maria if news'),
    ('defense_thesis',      '{maria,risk,steph}',     '{tax}',         'Defense thesis: all three core analysts required'),
    ('speculative_growth',  '{maria,risk}',           '{steph}',       'Speculative growth: Maria catalyst + Risk setup required, Steph for sizing'),
    ('growth_etf',          '{steph,risk}',           '{maria}',       'Growth ETF: Steph allocation + Risk technical required'),
    ('core_holding',        '{steph,risk}',           '{maria}',       'Core holding: Steph + Risk required, Maria if catalyst changed'),
    ('swing_trade',         '{maria,risk}',           '{steph,tax}',   'Swing trade: Maria catalyst + Risk technical required')
ON CONFLICT (strategy_type) DO NOTHING;

-- 5. Backfill maturity for existing symbols
INSERT INTO watchlist_analysis_maturity (symbol, analysis_stage, raw_data_ready, strategy_card_ready)
SELECT DISTINCT wi.symbol,
    CASE
        WHEN sc.symbol IS NOT NULL AND ar.symbol IS NOT NULL THEN 'specialist_review_partial'
        WHEN sc.symbol IS NOT NULL THEN 'strategy_card_ready'
        ELSE 'raw_data_only'
    END,
    TRUE,
    sc.symbol IS NOT NULL
FROM watchlist_items wi
LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
LEFT JOIN (SELECT DISTINCT symbol FROM watchlist_agent_results) ar ON ar.symbol = wi.symbol
WHERE wi.status <> 'removed'
ON CONFLICT (symbol) DO NOTHING;

-- Update completed agents from existing results
DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT symbol, array_agg(DISTINCT agent) as agents
        FROM watchlist_agent_results
        GROUP BY symbol
    LOOP
        UPDATE watchlist_analysis_maturity
        SET completed_agents = rec.agents,
            last_completed_agent = (SELECT agent FROM watchlist_agent_results WHERE symbol = rec.symbol ORDER BY created_at DESC LIMIT 1),
            last_completed_at = (SELECT created_at FROM watchlist_agent_results WHERE symbol = rec.symbol ORDER BY created_at DESC LIMIT 1)
        WHERE symbol = rec.symbol;
    END LOOP;
END $$;

COMMIT;
