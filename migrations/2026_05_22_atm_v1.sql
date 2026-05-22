-- ATM v1 (Automated Trade Mode) — Schema Migration
-- Date: 2026-05-22
-- Phase 0: Account registry
-- Phase 1: ATM state machine, decision log, config history, provenance columns

BEGIN;

-- ═══════════════════════════════════════════════════════════════════
-- Phase 0: Account registry
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS accounts (
    id              BIGSERIAL PRIMARY KEY,
    account_label   TEXT NOT NULL UNIQUE,
    broker          TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK (mode IN ('paper', 'live')),
    auto_execution_capable BOOLEAN NOT NULL DEFAULT false,
    equity_source   TEXT NOT NULL,
    routing_adapter TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes           TEXT
);

INSERT INTO accounts (account_label, broker, mode, auto_execution_capable,
                      equity_source, routing_adapter, enabled, notes) VALUES
('alpaca_paper',        'alpaca',   'paper', true,  'live_api',      'scripts.alpaca_paper_adapter', true,
 'Only auto-capable account at ATM v1 build time.'),
('schwab_rollover_ira', 'schwab',   'live',  false, 'holdings_json', NULL, false,
 'No routing adapter yet — manual execution only.'),
('schwab_roth_ira',     'schwab',   'live',  false, 'holdings_json', NULL, false,
 'No routing adapter yet — manual execution only.'),
('schwab_taxable',      'schwab',   'live',  false, 'holdings_json', NULL, false,
 'No routing adapter yet — manual execution only.'),
('fidelity_401k',       'fidelity', 'live',  false, 'holdings_json', NULL, false,
 'No routing adapter yet — manual execution only.')
ON CONFLICT (account_label) DO NOTHING;

-- target_account on proposals and trades
ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS target_account TEXT DEFAULT 'alpaca_paper';
ALTER TABLE paper_trades
    ADD COLUMN IF NOT EXISTS target_account TEXT DEFAULT 'alpaca_paper';

-- Backfill existing rows
UPDATE paper_trade_proposals SET target_account = 'alpaca_paper' WHERE target_account IS NULL;
UPDATE paper_trades SET target_account = 'alpaca_paper' WHERE target_account IS NULL;

-- ═══════════════════════════════════════════════════════════════════
-- Phase 1: ATM state machine + decision log
-- ═══════════════════════════════════════════════════════════════════

-- ATM state singleton
CREATE TABLE IF NOT EXISTS atm_state (
    id                      INT PRIMARY KEY DEFAULT 1,
    mode                    TEXT NOT NULL DEFAULT 'disabled'
                            CHECK (mode IN ('disabled', 'dry_run', 'active', 'paused')),
    paused_until            TIMESTAMPTZ,
    pause_reason            TEXT,
    last_state_change_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_state_change_by    TEXT NOT NULL DEFAULT 'system',
    last_evaluated_at       TIMESTAMPTZ,
    config_hash             TEXT,
    daily_loss_pause_armed  BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT singleton CHECK (id = 1)
);
INSERT INTO atm_state (id, mode) VALUES (1, 'disabled')
    ON CONFLICT (id) DO NOTHING;

-- State transition log
CREATE TABLE IF NOT EXISTS atm_state_events (
    id          BIGSERIAL PRIMARY KEY,
    event_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    old_mode    TEXT,
    new_mode    TEXT NOT NULL,
    changed_by  TEXT NOT NULL,
    reason      TEXT,
    config_hash TEXT
);

-- Decision log
CREATE TABLE IF NOT EXISTS atm_decision_log (
    id                      BIGSERIAL PRIMARY KEY,
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    proposal_id             BIGINT NOT NULL,
    symbol                  TEXT NOT NULL,
    strategy_id             TEXT NOT NULL,
    target_account          TEXT NOT NULL,
    account_broker          TEXT NOT NULL,
    account_mode            TEXT NOT NULL,
    decision                TEXT NOT NULL CHECK (decision IN (
        'approved', 'rejected', 'deferred',
        'dry_run_approved', 'dry_run_rejected',
        'force_approved', 'force_rejected', 'force_skipped'
    )),
    rejection_reasons       JSONB,
    classifier_health       NUMERIC(4,3),
    positions_open_account  INT,
    positions_open_total    INT,
    new_today_account       INT,
    new_today_total         INT,
    daily_pnl_pct_account   NUMERIC(6,3),
    daily_pnl_pct_aggregate NUMERIC(6,3),
    b1_excluded             BOOLEAN DEFAULT false,
    config_hash             TEXT NOT NULL,
    atm_mode                TEXT NOT NULL,
    trade_id                BIGINT
);
CREATE INDEX IF NOT EXISTS idx_atm_decisions_recent ON atm_decision_log (decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_atm_decisions_proposal ON atm_decision_log (proposal_id);
CREATE INDEX IF NOT EXISTS idx_atm_decisions_account ON atm_decision_log (target_account, decided_at DESC);

-- Config change history
CREATE TABLE IF NOT EXISTS atm_config_history (
    id          BIGSERIAL PRIMARY KEY,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by  TEXT NOT NULL,
    old_config  JSONB,
    new_config  JSONB NOT NULL,
    old_hash    TEXT,
    new_hash    TEXT NOT NULL,
    change_diff JSONB,
    backup_path TEXT
);

-- Per-proposal ATM action override
ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS atm_action TEXT
        CHECK (atm_action IN ('force_approve', 'force_reject', 'force_skip')),
    ADD COLUMN IF NOT EXISTS atm_action_set_by TEXT,
    ADD COLUMN IF NOT EXISTS atm_action_set_at TIMESTAMPTZ;

-- ATM provenance on trades
ALTER TABLE paper_trades
    ADD COLUMN IF NOT EXISTS atm_decision_id BIGINT,
    ADD COLUMN IF NOT EXISTS atm_config_hash TEXT,
    ADD COLUMN IF NOT EXISTS atm_during_b1 BOOLEAN DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_paper_trades_atm ON paper_trades (atm_decision_id)
    WHERE atm_decision_id IS NOT NULL;

COMMIT;
