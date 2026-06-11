-- Daily execution coaching queue (read-only analytics; advisory only; NO live-strategy/trading changes).
CREATE TABLE IF NOT EXISTS daily_execution_coaching_runs (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE, window_start DATE, window_end DATE, source_filter TEXT,
    trade_count INT, poor_count INT, weak_count INT, good_count INT,
    top_mistakes_json JSONB, top_symbols_json JSONB, top_strategy_families_json JSONB,
    summary TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS daily_execution_coaching_items (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES daily_execution_coaching_runs(id) ON DELETE CASCADE,
    rank INT, severity TEXT,
    item_type TEXT,   -- repeated_mistake | symbol_review | strategy_family_review | missed_runner | no_volume_entry | premature_exit | hypothesis_candidate
    symbol TEXT, strategy_family TEXT, source TEXT,
    trade_keys_json JSONB, sample_size INT,
    avg_capture_ratio NUMERIC, avg_missed_pct NUMERIC, avg_delta_ps NUMERIC,
    lesson TEXT, operator_action TEXT, evidence_json JSONB,
    status TEXT DEFAULT 'new',   -- new | reviewed | dismissed | promoted_to_shadow_research
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS daily_execution_grok_digests (
    id BIGSERIAL PRIMARY KEY, run_id BIGINT REFERENCES daily_execution_coaching_runs(id) ON DELETE CASCADE,
    model_lane TEXT, prompt_version TEXT, digest_json JSONB, review_status TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dec_items_run ON daily_execution_coaching_items (run_id, rank);
