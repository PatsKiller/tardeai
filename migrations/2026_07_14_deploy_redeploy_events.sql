-- Post-sale redeploy intelligence (advisory only — no broker execution)
-- Portfolio → Redeploy tab; event_key idempotent on trade_transactions dedupe

CREATE TABLE IF NOT EXISTS deploy_events (
    id BIGSERIAL PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    account TEXT NOT NULL,
    sold_at DATE NOT NULL,
    proceeds_usd NUMERIC,
    shares_sold NUMERIC,
    realized_pnl NUMERIC,
    instrument_type TEXT,
    proxy_symbol TEXT,
    proxy_sleeve TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    proceeds_settled BOOLEAN NOT NULL DEFAULT FALSE,
    cash_visible_usd NUMERIC,
    lookthrough_delta JSONB NOT NULL DEFAULT '[]'::jsonb,
    redeploy_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL DEFAULT 'live_detect',
    txn_ref TEXT,
    txn_id INTEGER,
    dismiss_reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('open', 'settled', 'dismissed', 'approved')),
    CHECK (source IN ('live_detect', 'backfill', 'manual'))
);

CREATE INDEX IF NOT EXISTS idx_deploy_events_status ON deploy_events(status, sold_at DESC);
CREATE INDEX IF NOT EXISTS idx_deploy_events_account ON deploy_events(account, sold_at DESC);
CREATE INDEX IF NOT EXISTS idx_deploy_events_symbol ON deploy_events(UPPER(symbol), sold_at DESC);

CREATE TABLE IF NOT EXISTS deploy_plans (
    id BIGSERIAL PRIMARY KEY,
    deploy_event_id BIGINT NOT NULL REFERENCES deploy_events(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    impact JSONB NOT NULL DEFAULT '{}'::jsonb,
    redeploy_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
    oversight JSONB NOT NULL DEFAULT '{}'::jsonb,
    advice TEXT,
    advice_provider TEXT,
    target_directives JSONB NOT NULL DEFAULT '[]'::jsonb,
    learning_obs_id BIGINT,
    directive_ids BIGINT[],
    status TEXT NOT NULL DEFAULT 'approved',
    CHECK (status IN ('approved', 'draft'))
);

CREATE INDEX IF NOT EXISTS idx_deploy_plans_event ON deploy_plans(deploy_event_id);

CREATE TABLE IF NOT EXISTS deploy_oversight_runs (
    id BIGSERIAL PRIMARY KEY,
    deploy_event_id BIGINT NOT NULL REFERENCES deploy_events(id) ON DELETE CASCADE,
    lane TEXT NOT NULL,
    verdict TEXT,
    answer TEXT,
    model TEXT,
    ok BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (lane IN ('grok', 'chatgpt'))
);

CREATE INDEX IF NOT EXISTS idx_deploy_oversight_event ON deploy_oversight_runs(deploy_event_id, ran_at DESC);