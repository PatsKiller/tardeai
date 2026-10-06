-- Positions store, phase 1 — build in shadow (2026-10-06).
--
-- Plan of record: docs/architecture/POSITIONS_SOURCE_OF_TRUTH_PLAN_2026-10-05.md (operator approved
-- phase 1 on 2026-10-06: "yes start phase 1 and fix all of it").
--
-- Five tables that hold ONLY what brokers report. No column here is a market price used as truth:
-- price, value, day change and unrealized P&L are computed at read time from the data-broker quote
-- (scripts/lib/portfolio_positions.py). broker_market_value is the broker's own reported figure,
-- kept for reconciliation only, always next to its captured_at.
--
-- Single writer: scripts/positions_sync.py. tests/test_positions_store_phase1_20261006.py fails the
-- build if any other file writes these tables.
--
-- SHADOW: nothing reads these tables in phase 1. holdings.json remains the served store until the
-- phase 3 reader batches are approved one by one.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS only. Nothing is dropped or rewritten.

CREATE TABLE IF NOT EXISTS positions_sync_runs (
    run_id            BIGSERIAL PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'complete', 'partial', 'failed')),
    promoted          BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE only when this run became positions_current
    accounts_ok       TEXT[] NOT NULL DEFAULT '{}',
    accounts_failed   JSONB NOT NULL DEFAULT '{}'::jsonb, -- {account_key: error}
    accounts          JSONB NOT NULL DEFAULT '{}'::jsonb, -- {account_key: {cash, equity, source, captured_at}}
    position_rows     INTEGER NOT NULL DEFAULT 0,
    lot_rows          INTEGER NOT NULL DEFAULT 0,
    realized_rows     INTEGER NOT NULL DEFAULT 0,
    writer            TEXT NOT NULL DEFAULT 'scripts/positions_sync.py',
    git_sha           TEXT,
    notes             TEXT
);
CREATE INDEX IF NOT EXISTS positions_sync_runs_finished_idx
    ON positions_sync_runs (finished_at DESC) WHERE status = 'complete';

-- Append-only: every broker position row seen by every run (incl. a CASH row per account).
CREATE TABLE IF NOT EXISTS position_snapshots (
    id                    BIGSERIAL PRIMARY KEY,
    sync_run_id           BIGINT NOT NULL REFERENCES positions_sync_runs(run_id),
    account_key           TEXT NOT NULL,
    broker                TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    qty                   NUMERIC NOT NULL,
    cost_basis_total      NUMERIC,            -- NULL = broker does not report basis (never guessed)
    avg_cost              NUMERIC,
    broker_market_value   NUMERIC,            -- broker-reported, reconciliation only
    is_cash               BOOLEAN NOT NULL DEFAULT FALSE,
    asset_type            TEXT,
    source                TEXT NOT NULL,      -- e.g. schwab_api, alpaca_live_api, moomoo_opend, manual
    captured_at           TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS position_snapshots_run_idx ON position_snapshots (sync_run_id);
CREATE INDEX IF NOT EXISTS position_snapshots_acct_sym_idx
    ON position_snapshots (account_key, symbol, captured_at DESC);

-- One row per account + symbol from the latest promoted run (derived; rewritten atomically).
CREATE TABLE IF NOT EXISTS positions_current (
    account_key           TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    broker                TEXT NOT NULL,
    qty                   NUMERIC NOT NULL,
    cost_basis_total      NUMERIC,
    avg_cost              NUMERIC,
    broker_market_value   NUMERIC,
    is_cash               BOOLEAN NOT NULL DEFAULT FALSE,
    asset_type            TEXT,
    lots_count            INTEGER NOT NULL DEFAULT 0,
    lots_basis_known      BOOLEAN,            -- every open lot has a broker-ledger unit cost
    source                TEXT NOT NULL,
    as_of                 TIMESTAMPTZ NOT NULL,
    sync_run_id           BIGINT NOT NULL REFERENCES positions_sync_runs(run_id),
    PRIMARY KEY (account_key, symbol)
);

-- Open lots rebuilt each run from the broker transaction ledger (trade_transactions), FIFO.
CREATE TABLE IF NOT EXISTS position_lots (
    id                BIGSERIAL PRIMARY KEY,
    sync_run_id       BIGINT NOT NULL REFERENCES positions_sync_runs(run_id),
    account_key       TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    acquired_on       DATE NOT NULL,
    acquire_action    TEXT NOT NULL,      -- Buy, Reinvest Shares, Security Transfer, ...
    qty_open          NUMERIC NOT NULL,
    unit_cost         NUMERIC,            -- NULL when the ledger carries no basis (transfers in)
    basis_known       BOOLEAN NOT NULL,
    source_txn_id     INTEGER
);
CREATE INDEX IF NOT EXISTS position_lots_acct_sym_idx ON position_lots (account_key, symbol);

-- Every sell matched to the lots it closed (FIFO), rebuilt each run.
CREATE TABLE IF NOT EXISTS realized_lots (
    id                BIGSERIAL PRIMARY KEY,
    sync_run_id       BIGINT NOT NULL REFERENCES positions_sync_runs(run_id),
    account_key       TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    sold_on           DATE NOT NULL,
    qty               NUMERIC NOT NULL,
    proceeds          NUMERIC NOT NULL,   -- net of fees, pro-rated per matched lot
    cost              NUMERIC,            -- NULL when the matched lot's basis is unknown
    realized_pl       NUMERIC,            -- NULL when cost is NULL — never a guessed zero
    acquired_on       DATE,
    basis_known       BOOLEAN NOT NULL,
    method            TEXT NOT NULL DEFAULT 'fifo',
    sell_txn_id       INTEGER,
    lot_txn_id        INTEGER
);
CREATE INDEX IF NOT EXISTS realized_lots_acct_sym_idx ON realized_lots (account_key, symbol, sold_on);
