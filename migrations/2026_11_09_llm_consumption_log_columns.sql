-- llm_consumption_log / llm_process_config / llm_cost_reservations — the full LLM accounting schema
-- (2026-11-09, LQ-20261107-1686).
--
-- scripts/lib/llm_consumption.py::ensure_schema() used to create these tables and add these fourteen
-- columns with CREATE ... IF NOT EXISTS and ALTER TABLE ... ADD COLUMN IF NOT EXISTS on EVERY process
-- start. IF NOT EXISTS suppresses the error, not the lock: each ALTER asked for an ACCESS EXCLUSIVE lock
-- on llm_consumption_log — the table every LLM call appends to — and on llm_process_config. Measured
-- consequence, 2026-11-09 14:18–15:19 ET: 124 lock timeouts and 5 deadlocks, because every reader and
-- writer of those tables (3 s lock_timeout, db_adapter) queued behind a statement with nothing to do.
--
-- Two things changed with this file:
--   1. the schema now lives here, so it can be applied once, out of band, like every other table; and
--   2. ensure_schema() asks the catalog first (lib.ddl_guard.relation_exists / column_exists) and
--      issues DDL only for what is genuinely absent — nothing at all on an up-to-date database.
--
-- Verified read-only against production on 2026-11-09 21:3xZ: llm_consumption_log 30 columns,
-- llm_process_config 9, llm_cost_reservations 9, all three indexes present. Applying this file there
-- is a no-op; it exists so a fresh database can be brought to the same shape in one statement batch.
--
-- Additive and idempotent. No .down.sql: every statement here adds structure to an append-only
-- accounting ledger, and dropping those columns would destroy rows that are the only record of spend.
BEGIN;

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
    mode TEXT NOT NULL DEFAULT 'manual',
    allowed_lanes TEXT[] DEFAULT ARRAY['grok','chatgpt','deepseek-flash','deepseek-v4-flash','deepseek-v4-pro','fast','pro','pro_think'],
    daily_soft_cap INT,
    notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_consumption_log_created
    ON llm_consumption_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_consumption_log_process
    ON llm_consumption_log (process_id, created_at DESC);

-- Paid-token accounting columns added after the first deploy.
ALTER TABLE llm_consumption_log
    ADD COLUMN IF NOT EXISTS relative_units NUMERIC(12,6) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_basis TEXT,
    ADD COLUMN IF NOT EXISTS pricing_effective_at TEXT,
    ADD COLUMN IF NOT EXISTS reasoning_tokens INT,
    ADD COLUMN IF NOT EXISTS cache_hit_tokens INT,
    ADD COLUMN IF NOT EXISTS cache_miss_tokens INT,
    ADD COLUMN IF NOT EXISTS requested_policy TEXT,
    ADD COLUMN IF NOT EXISTS executed_policy TEXT,
    ADD COLUMN IF NOT EXISTS requested_model_id TEXT,
    ADD COLUMN IF NOT EXISTS returned_model TEXT,
    ADD COLUMN IF NOT EXISTS thinking TEXT,
    ADD COLUMN IF NOT EXISTS reasoning_effort TEXT,
    ADD COLUMN IF NOT EXISTS provider_request_id TEXT;

ALTER TABLE llm_process_config
    ADD COLUMN IF NOT EXISTS daily_cost_cap_usd NUMERIC(12,4);

CREATE TABLE IF NOT EXISTS llm_cost_reservations (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    process_id TEXT NOT NULL,
    projected_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    actual_usd NUMERIC(12,6),
    status TEXT NOT NULL DEFAULT 'reserved',
    model_id TEXT,
    request_key TEXT,
    metadata_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_llm_cost_reservations_process
    ON llm_cost_reservations (process_id, created_at DESC);

COMMIT;
