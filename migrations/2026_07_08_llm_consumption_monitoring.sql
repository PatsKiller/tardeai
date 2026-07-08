-- LLM consumption monitoring: per-process Automated/Manual gating + call audit log.
-- Free OAuth lanes only (Grok :8645, ChatGPT :8646). Additive-only.

CREATE TABLE IF NOT EXISTS llm_consumption_log (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_lane TEXT NOT NULL,
    model_name TEXT,
    process_id TEXT NOT NULL,
    process_name TEXT,
    task_summary TEXT,
    trigger_mode TEXT NOT NULL DEFAULT 'automated',
    prompt_chars INT,
    response_chars INT,
    tokens_in INT,
    tokens_out INT,
    estimated_cost_usd NUMERIC(12,6) DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    duration_ms INT,
    metadata_json JSONB
);

CREATE TABLE IF NOT EXISTS llm_process_config (
    process_id TEXT PRIMARY KEY,
    process_name TEXT NOT NULL,
    category TEXT,
    mode TEXT NOT NULL DEFAULT 'manual' CHECK (mode IN ('automated', 'manual')),
    allowed_lanes TEXT[] DEFAULT ARRAY['grok','chatgpt'],
    daily_soft_cap INT,
    notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_consumption_log_created ON llm_consumption_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_consumption_log_process ON llm_consumption_log (process_id, created_at DESC);