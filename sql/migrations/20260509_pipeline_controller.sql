-- Pipeline Controller: dependency-aware orchestration
-- 2026-05-09 Hardening Sprint Workstream B

CREATE TABLE IF NOT EXISTS pipeline_definitions (
    id          BIGSERIAL PRIMARY KEY,
    pipeline_key TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    active      BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_stages (
    id                      BIGSERIAL PRIMARY KEY,
    pipeline_key            TEXT NOT NULL,
    stage_key               TEXT NOT NULL,
    group_key               TEXT,
    name                    TEXT NOT NULL,
    command                 TEXT NOT NULL,
    working_dir             TEXT,
    timeout_seconds         INTEGER DEFAULT 1800,
    max_retries             INTEGER DEFAULT 1,
    retry_backoff_seconds   INTEGER DEFAULT 60,
    sla_seconds             INTEGER,
    active                  BOOLEAN DEFAULT true,
    sort_order              INTEGER DEFAULT 0,
    can_degrade             BOOLEAN DEFAULT false,
    degradation_policy      TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(pipeline_key, stage_key)
);

CREATE TABLE IF NOT EXISTS pipeline_stage_dependencies (
    id                      BIGSERIAL PRIMARY KEY,
    pipeline_key            TEXT NOT NULL,
    stage_key               TEXT NOT NULL,
    depends_on_stage_key    TEXT NOT NULL,
    dependency_type         TEXT DEFAULT 'success',
    UNIQUE(pipeline_key, stage_key, depends_on_stage_key)
);

-- Drop old pipeline_runs if it conflicts, but only if safe
-- The existing table may have different schema
DO $$
BEGIN
    -- Check if old pipeline_runs exists with incompatible schema
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'pipeline_runs' AND table_schema = 'public') THEN
        -- Check if it already has run_id column
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'pipeline_runs' AND column_name = 'run_id') THEN
            -- Old schema — rename it, create new
            ALTER TABLE pipeline_runs RENAME TO pipeline_runs_legacy;
        END IF;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT UNIQUE NOT NULL,
    pipeline_key    TEXT NOT NULL,
    run_label       TEXT,
    status          TEXT NOT NULL DEFAULT 'created',
    trigger_source  TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_seconds NUMERIC,
    summary         JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_stage_runs (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    pipeline_key        TEXT NOT NULL,
    stage_key           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    attempt             INTEGER DEFAULT 0,
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    duration_seconds    NUMERIC,
    exit_code           INTEGER,
    error_type          TEXT,
    error_message       TEXT,
    log_path            TEXT,
    stdout_tail         TEXT,
    stderr_tail         TEXT,
    sla_status          TEXT,
    dependency_blockers JSONB,
    result              JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_id, stage_key, attempt)
);

CREATE TABLE IF NOT EXISTS pipeline_events (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT,
    stage_key   TEXT,
    event_type  TEXT NOT NULL,
    severity    TEXT DEFAULT 'info',
    message     TEXT,
    payload     JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_stage_runs_run ON pipeline_stage_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_run ON pipeline_events(run_id, created_at);

-- Seed the daily pipeline definition
INSERT INTO pipeline_definitions (pipeline_key, name, description)
VALUES ('daily', 'Daily Trading Pipeline', '31-stage pipeline from data collection through overnight')
ON CONFLICT (pipeline_key) DO NOTHING;
