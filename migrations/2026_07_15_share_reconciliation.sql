-- Share reconciliation (dividend reinvestment / broker drift)
-- Open tasks + immutable audit log. Holdings SSOT remains holdings.json;
-- these tables track operator-approved system share updates.

CREATE TABLE IF NOT EXISTS position_share_drift (
    id              SERIAL PRIMARY KEY,
    account_key     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    system_shares   NUMERIC NOT NULL,
    broker_shares   NUMERIC NOT NULL,
    drift_amount    NUMERIC NOT NULL,
    source          TEXT NOT NULL DEFAULT 'unknown',
    -- dividend_reinvestment | corporate_action | manual_deposit | missed_trade | api_sync | unknown
    status          TEXT NOT NULL DEFAULT 'open',
    -- open | snoozed | reconciled | dismissed
    snooze_until    TIMESTAMPTZ,
    notes           TEXT,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- one open/snoozed task per lot via partial unique index below
);

-- Allow multiple historical rows; enforce at most one open/snoozed per lot
DROP INDEX IF EXISTS ux_position_share_drift_open_lot;
CREATE UNIQUE INDEX ux_position_share_drift_open_lot
    ON position_share_drift (account_key, symbol)
    WHERE status IN ('open', 'snoozed');

CREATE INDEX IF NOT EXISTS ix_position_share_drift_status
    ON position_share_drift (status, detected_at DESC);

CREATE TABLE IF NOT EXISTS position_reconciliation_log (
    id                      SERIAL PRIMARY KEY,
    account_key             TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    previous_system_shares  NUMERIC NOT NULL,
    new_system_shares       NUMERIC NOT NULL,
    broker_shares_at_time   NUMERIC,
    drift_amount            NUMERIC NOT NULL,
    source                  TEXT NOT NULL,
    -- dividend_reinvestment | corporate_action | manual | api_sync | missed_trade | unknown
    reconciled_by           TEXT NOT NULL DEFAULT 'operator',
    reconciled_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes                   TEXT,
    impact_json             JSONB,
    drift_task_id           INTEGER REFERENCES position_share_drift(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_position_recon_log_lot
    ON position_reconciliation_log (account_key, symbol, reconciled_at DESC);

COMMENT ON TABLE position_share_drift IS
  'Open share-count drift tasks (system_shares vs broker_actual_shares). Approval-based.';
COMMENT ON TABLE position_reconciliation_log IS
  'Immutable audit of system share reconciliations (tax / stop debugging).';
