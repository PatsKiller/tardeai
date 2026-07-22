-- Watch Decision Desk V5 — server-owned refresh run/job system (2026-07-22)
-- Runs group an operator/scheduler request; jobs are per-symbol units with
-- idempotency, per-symbol serialization, and before/after packet evidence.

CREATE TABLE IF NOT EXISTS watch_decision_refresh_runs (
    run_id            BIGSERIAL PRIMARY KEY,
    requested_by      TEXT NOT NULL DEFAULT 'operator',
    reason            TEXT NOT NULL DEFAULT '',
    scope             TEXT NOT NULL CHECK (scope IN ('INPUTS_ONLY','AFFECTED_DIMENSIONS','FULL_STRATEGY')),
    analysis_tier     TEXT NOT NULL CHECK (analysis_tier IN ('LOCAL_QUANT','STANDARD_BLIND','PREMIUM_REVIEW')),
    include_options   BOOLEAN NOT NULL DEFAULT FALSE,
    force             BOOLEAN NOT NULL DEFAULT FALSE,
    symbols_requested INT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'QUEUED'
                      CHECK (state IN ('QUEUED','RUNNING','COMPLETE','PARTIAL','FAILED','CANCELLED')),
    policy_version    TEXT,
    source_commit_sha TEXT,
    estimated_lane_calls    INT NOT NULL DEFAULT 0,
    estimated_paid_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
    actual_lane_calls       INT NOT NULL DEFAULT 0,
    actual_paid_cost_usd    NUMERIC(10,4) NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS watch_decision_refresh_jobs (
    job_id            BIGSERIAL PRIMARY KEY,
    run_id            BIGINT NOT NULL REFERENCES watch_decision_refresh_runs(run_id) ON DELETE CASCADE,
    symbol            TEXT NOT NULL,
    scope             TEXT NOT NULL,
    analysis_tier     TEXT NOT NULL,
    priority          INT NOT NULL DEFAULT 100,
    -- one live job per (symbol, scope, tier, input-hash) — duplicates are SKIPPED_CURRENT
    idempotency_key   TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'QUEUED'
                      CHECK (state IN ('QUEUED','RUNNING','COMPLETE','PARTIAL','FAILED',
                                       'CANCELLED','SKIPPED_CURRENT','SKIPPED_LOCKED')),
    stage             TEXT,
    stages            JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_hash_before TEXT,
    input_hash_after  TEXT,
    packet_id_before  BIGINT,
    packet_id_after   BIGINT,
    decision_run_id   BIGINT,          -- shadow_strategy_job decision_runs.run_id when a rebuild ran
    invalidation_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    refreshed_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_calls      JSONB NOT NULL DEFAULT '{}'::jsonb,
    lane_calls        INT NOT NULL DEFAULT 0,
    failure_class     TEXT,
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    heartbeat_at      TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_wdr_jobs_claim
    ON watch_decision_refresh_jobs (state, priority, created_at) WHERE state = 'QUEUED';
CREATE INDEX IF NOT EXISTS idx_wdr_jobs_run ON watch_decision_refresh_jobs (run_id);
CREATE INDEX IF NOT EXISTS idx_wdr_jobs_symbol_live
    ON watch_decision_refresh_jobs (symbol) WHERE state IN ('QUEUED','RUNNING');
CREATE UNIQUE INDEX IF NOT EXISTS idx_wdr_jobs_idem_live
    ON watch_decision_refresh_jobs (idempotency_key) WHERE state IN ('QUEUED','RUNNING');
