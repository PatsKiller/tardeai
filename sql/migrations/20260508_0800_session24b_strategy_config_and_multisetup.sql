-- Session 24B: Strategy Config Versioning + Multi-Setup Routing
-- Date: 2026-05-08

CREATE TABLE IF NOT EXISTS strategy_config_versions (
    id SERIAL PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    version TEXT,
    config_hash TEXT NOT NULL,
    file_path TEXT,
    status TEXT,
    loaded_at TIMESTAMPTZ DEFAULT NOW(),
    loaded_by TEXT DEFAULT 'strategy_config_loader',
    config_snapshot JSONB,
    UNIQUE(strategy_id, config_hash)
);

CREATE TABLE IF NOT EXISTS strategy_setup_matches (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    source_signal_id INTEGER,
    proposal_id INTEGER,
    run_label TEXT,
    strategy_id TEXT NOT NULL,
    setup_class TEXT,
    match_score NUMERIC,
    match_status TEXT,
    criteria_met JSONB,
    criteria_failed JSONB,
    disqualifiers_hit JSONB,
    missing_data JSONB,
    is_primary BOOLEAN DEFAULT false,
    priority_rank INTEGER,
    reason TEXT,
    config_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ssm_symbol_created
ON strategy_setup_matches(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ssm_proposal
ON strategy_setup_matches(proposal_id, created_at DESC);

CREATE TABLE IF NOT EXISTS strategy_prompt_context_cache (
    id SERIAL PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    config_hash TEXT,
    prompt_context TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_id, config_hash)
);

ALTER TABLE strategy_registry
ADD COLUMN IF NOT EXISTS config_hash TEXT,
ADD COLUMN IF NOT EXISTS yaml_version TEXT,
ADD COLUMN IF NOT EXISTS rules_source TEXT DEFAULT 'yaml',
ADD COLUMN IF NOT EXISTS last_yaml_sync_at TIMESTAMPTZ;

ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS primary_strategy_id TEXT,
ADD COLUMN IF NOT EXISTS secondary_strategy_ids JSONB,
ADD COLUMN IF NOT EXISTS setup_stack JSONB,
ADD COLUMN IF NOT EXISTS strategy_config_hash TEXT,
ADD COLUMN IF NOT EXISTS strategy_prompt_context TEXT;

ALTER TABLE strategy_signals
ADD COLUMN IF NOT EXISTS setup_stack JSONB,
ADD COLUMN IF NOT EXISTS primary_strategy_id TEXT,
ADD COLUMN IF NOT EXISTS secondary_strategy_ids JSONB,
ADD COLUMN IF NOT EXISTS strategy_config_hash TEXT;
