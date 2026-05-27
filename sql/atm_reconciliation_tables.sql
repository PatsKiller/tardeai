-- atm_reconciliation_tables.sql v2.0
-- Audit-only reconciliation tables for ATM paper-trade position drift.
-- Install target: sql/atm_reconciliation_tables.sql or existing repo migration path.


CREATE TABLE IF NOT EXISTS atm_position_reconciliation_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT UNIQUE NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    mode TEXT NOT NULL DEFAULT 'audit_only',
    journal_source TEXT,
    db_open_count INTEGER NOT NULL DEFAULT 0,
    journal_open_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    mismatch_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    mirror_account_count INTEGER NOT NULL DEFAULT 0,
    missing_identifier_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'unknown',
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE INDEX IF NOT EXISTS idx_atm_pos_recon_runs_started_at
    ON atm_position_reconciliation_runs(started_at DESC);


CREATE INDEX IF NOT EXISTS idx_atm_pos_recon_runs_status
    ON atm_position_reconciliation_runs(status);


CREATE TABLE IF NOT EXISTS atm_position_reconciliation_items (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES atm_position_reconciliation_runs(run_id) ON DELETE CASCADE,
    paper_trade_id BIGINT,
    lifecycle_id TEXT,
    symbol TEXT,
    strategy_id TEXT,
    account TEXT,
    broker_order_id TEXT,
    journal_match_key TEXT,
    classification TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    reason TEXT,
    recommended_action TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE INDEX IF NOT EXISTS idx_atm_pos_recon_items_run_id
    ON atm_position_reconciliation_items(run_id);


CREATE INDEX IF NOT EXISTS idx_atm_pos_recon_items_symbol
    ON atm_position_reconciliation_items(symbol);


CREATE INDEX IF NOT EXISTS idx_atm_pos_recon_items_classification
    ON atm_position_reconciliation_items(classification);


CREATE INDEX IF NOT EXISTS idx_atm_pos_recon_items_severity
    ON atm_position_reconciliation_items(severity);


-- SQLite-compatible variant, use only if the project DB is SQLite:
-- CREATE TABLE IF NOT EXISTS atm_position_reconciliation_runs (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     run_id TEXT UNIQUE NOT NULL,
--     started_at TEXT NOT NULL,
--     completed_at TEXT,
--     mode TEXT NOT NULL DEFAULT 'audit_only',
--     journal_source TEXT,
--     db_open_count INTEGER NOT NULL DEFAULT 0,
--     journal_open_count INTEGER NOT NULL DEFAULT 0,
--     matched_count INTEGER NOT NULL DEFAULT 0,
--     mismatch_count INTEGER NOT NULL DEFAULT 0,
--     duplicate_count INTEGER NOT NULL DEFAULT 0,
--     mirror_account_count INTEGER NOT NULL DEFAULT 0,
--     missing_identifier_count INTEGER NOT NULL DEFAULT 0,
--     status TEXT NOT NULL DEFAULT 'unknown',
--     payload TEXT,
--     created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
--
-- CREATE TABLE IF NOT EXISTS atm_position_reconciliation_items (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     run_id TEXT NOT NULL,
--     paper_trade_id INTEGER,
--     lifecycle_id TEXT,
--     symbol TEXT,
--     strategy_id TEXT,
--     account TEXT,
--     broker_order_id TEXT,
--     journal_match_key TEXT,
--     classification TEXT NOT NULL,
--     severity TEXT NOT NULL DEFAULT 'info',
--     reason TEXT,
--     recommended_action TEXT,
--     payload TEXT,
--     created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );


-- Rollback:
-- DROP TABLE IF EXISTS atm_position_reconciliation_items;
-- DROP TABLE IF EXISTS atm_position_reconciliation_runs;