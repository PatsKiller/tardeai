CREATE TABLE IF NOT EXISTS state_freshness_history (
    id SERIAL PRIMARY KEY,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    state_file TEXT NOT NULL,
    exists_flag BOOLEAN NOT NULL DEFAULT FALSE,
    ok BOOLEAN NOT NULL DEFAULT FALSE,
    age_hours NUMERIC(10,2),
    max_age_hours NUMERIC(10,2),
    source_script TEXT,
    agent_checked_at TIMESTAMPTZ,
    producer_status TEXT,
    file_mtime TIMESTAMPTZ,
    file_size_bytes BIGINT,
    mode TEXT,
    issues JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_state_freshness_history_file_time
    ON state_freshness_history (state_file, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_state_freshness_history_ok_time
    ON state_freshness_history (ok, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_state_freshness_history_source
    ON state_freshness_history (source_script, checked_at DESC);

CREATE OR REPLACE VIEW latest_state_freshness AS
SELECT DISTINCT ON (state_file)
    state_file,
    checked_at,
    exists_flag,
    ok,
    age_hours,
    max_age_hours,
    source_script,
    agent_checked_at,
    producer_status,
    file_mtime,
    file_size_bytes,
    mode,
    issues,
    metadata
FROM state_freshness_history
ORDER BY state_file, checked_at DESC;
