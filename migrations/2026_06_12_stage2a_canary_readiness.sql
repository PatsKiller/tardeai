-- Stage 2a readiness (2026-06-12): canary analytics exclusion + read-only shadow-recon / activity capture.
-- READ-ONLY program: nothing here creates a write path to Schwab — these tables hold OUR observations.

-- Part A2: canary tag on real-account round-trips. Sticky once true (ingest never un-tags).
ALTER TABLE schwab_round_trips ADD COLUMN IF NOT EXISTS canary BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_srt_canary ON schwab_round_trips (canary) WHERE canary;

-- Part A1: shadow-reconciliation harness (observed Schwab order vs translator-predicted payload).
CREATE TABLE IF NOT EXISTS schwab_shadow_recon_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accounts TEXT[] NOT NULL,
    orders_seen INT NOT NULL DEFAULT 0,
    matched INT NOT NULL DEFAULT 0,
    mismatched INT NOT NULL DEFAULT 0,
    unmatched INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',          -- ok | error
    detail TEXT
);
CREATE TABLE IF NOT EXISTS schwab_shadow_recon_items (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES schwab_shadow_recon_runs(id) ON DELETE CASCADE,
    account_key TEXT NOT NULL,
    broker_order_id TEXT,
    symbol TEXT,
    intent_id UUID,                              -- matched draft intent, when one exists
    verdict TEXT NOT NULL,                       -- match | rename_only | mismatch | unmatched_order | unmatched_intent
    diff JSONB,                                  -- field-level diff (empty object = exact match)
    observed JSONB,                              -- normalized Schwab representation (read-back)
    predicted JSONB,                             -- translator-predicted payload
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ssri_run ON schwab_shadow_recon_items (run_id);
CREATE INDEX IF NOT EXISTS idx_ssri_order ON schwab_shadow_recon_items (broker_order_id, created_at DESC);

-- Part A3: poll-based ACCT_ACTIVITY capture (fills/status changes), read-only, dedup on activity_key.
CREATE TABLE IF NOT EXISTS schwab_activity_log (
    id BIGSERIAL PRIMARY KEY,
    account_key TEXT NOT NULL,
    activity_key TEXT NOT NULL UNIQUE,           -- dedupe: account|kind|broker id|status-or-time
    kind TEXT NOT NULL,                          -- order_status | transaction
    broker_order_id TEXT,
    symbol TEXT,
    status TEXT,
    payload JSONB NOT NULL,
    event_time TIMESTAMPTZ,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sal_acct ON schwab_activity_log (account_key, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_sal_symbol ON schwab_activity_log (symbol, captured_at DESC);
