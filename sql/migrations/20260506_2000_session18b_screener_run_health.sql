-- Session 18b: Screener run health tracking
-- Tracks each screener run's completeness and health status

CREATE TABLE IF NOT EXISTS screener_run_health (
    id SERIAL PRIMARY KEY,
    run_label TEXT,
    run_date DATE DEFAULT CURRENT_DATE,
    source TEXT DEFAULT 'finviz',
    expected_min_symbols INTEGER DEFAULT 40,
    target_symbols INTEGER DEFAULT 60,
    symbols_scanned INTEGER DEFAULT 0,
    go_count INTEGER DEFAULT 0,
    wait_count INTEGER DEFAULT 0,
    no_go_count INTEGER DEFAULT 0,
    raw_rows INTEGER DEFAULT 0,
    normalized_rows INTEGER DEFAULT 0,
    deduped_symbols INTEGER DEFAULT 0,
    status TEXT DEFAULT 'UNKNOWN',
    reason_codes JSONB,
    input_snapshot JSONB,
    output_snapshot JSONB,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screener_run_health_run
ON screener_run_health(run_date, run_label);

CREATE INDEX IF NOT EXISTS idx_screener_run_health_status
ON screener_run_health(status, created_at DESC);
