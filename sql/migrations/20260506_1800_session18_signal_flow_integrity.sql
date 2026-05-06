-- Session 18: Signal Flow Integrity
-- Pipeline wiring: trade_ai_scans → strategy_signals → Strategy Desk

-- 2.1 signal_flow_audit
CREATE TABLE IF NOT EXISTS signal_flow_audit (
    id SERIAL PRIMARY KEY,
    run_label TEXT,
    run_date DATE,
    source_component TEXT NOT NULL,
    go_count INTEGER DEFAULT 0,
    aplus_count INTEGER DEFAULT 0,
    strategy_signals_before INTEGER DEFAULT 0,
    strategy_signals_after INTEGER DEFAULT 0,
    inserted_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    status TEXT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_flow_audit_run
ON signal_flow_audit(run_date, run_label, created_at DESC);

-- 2.2 strategy_signals lineage columns
ALTER TABLE strategy_signals
ADD COLUMN IF NOT EXISTS source_table TEXT,
ADD COLUMN IF NOT EXISTS source_record_id TEXT,
ADD COLUMN IF NOT EXISTS scan_run_label TEXT,
ADD COLUMN IF NOT EXISTS screener_label TEXT,
ADD COLUMN IF NOT EXISTS discovery_source TEXT,
ADD COLUMN IF NOT EXISTS sync_created_by TEXT,
ADD COLUMN IF NOT EXISTS sync_run_id TEXT;
