-- Options lifecycle monitor PR1: monitored positions + snapshots + alerts.
-- Multi-broker ready (Alpaca paper first; Fidelity manual / Schwab later).
-- Additive + idempotent. Advisory only — no order submit paths.

CREATE TABLE IF NOT EXISTS options_monitored_positions (
    id                    BIGSERIAL PRIMARY KEY,
    proposal_id           TEXT UNIQUE,
    broker                TEXT NOT NULL DEFAULT 'alpaca',
    execution_route       TEXT,              -- alpaca_paper | fidelity_manual | schwab_live | paper_model
    alpaca_order_id       TEXT,
    alpaca_position_id    TEXT,
    symbol                TEXT,
    underlying_symbol     TEXT,
    option_symbol         TEXT,
    strategy              TEXT,
    side                  TEXT,
    option_type           TEXT,
    strike                NUMERIC,
    expiration            DATE,
    contracts             INT NOT NULL DEFAULT 1,
    entry_limit           NUMERIC,
    entry_fill_price      NUMERIC,
    entry_debit_credit    TEXT,              -- debit | credit
    entry_underlying_price NUMERIC,
    entry_delta           NUMERIC,
    entry_gamma           NUMERIC,
    entry_theta           NUMERIC,
    entry_vega            NUMERIC,
    entry_iv              NUMERIC,
    entry_spread_pct      NUMERIC,
    entry_oi              INT,
    entry_volume          INT,
    opened_at             TIMESTAMPTZ,
    status                TEXT NOT NULL DEFAULT 'OPEN',
    paper_only            BOOLEAN NOT NULL DEFAULT TRUE,
    live_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    meta_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT options_monitored_positions_status_chk CHECK (status IN (
        'OPEN', 'CLOSING_REQUESTED', 'CLOSED', 'EXPIRED', 'ASSIGNED', 'ERROR'
    ))
);

CREATE INDEX IF NOT EXISTS idx_omp_status_open
    ON options_monitored_positions (status) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_omp_broker_symbol
    ON options_monitored_positions (broker, underlying_symbol);
CREATE INDEX IF NOT EXISTS idx_omp_opened
    ON options_monitored_positions (opened_at DESC);

CREATE TABLE IF NOT EXISTS options_monitored_position_snapshots (
    id                    BIGSERIAL PRIMARY KEY,
    position_id           BIGINT NOT NULL REFERENCES options_monitored_positions(id) ON DELETE CASCADE,
    snapshot_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    underlying_price      NUMERIC,
    option_bid            NUMERIC,
    option_ask            NUMERIC,
    option_mid            NUMERIC,
    option_mark           NUMERIC,
    spread_pct            NUMERIC,
    delta                 NUMERIC,
    gamma                 NUMERIC,
    theta                 NUMERIC,
    vega                  NUMERIC,
    rho                   NUMERIC,
    iv                    NUMERIC,
    intrinsic_value       NUMERIC,
    extrinsic_value       NUMERIC,
    dte                   INT,
    open_interest           INT,
    volume                INT,
    market_value          NUMERIC,
    unrealized_pnl        NUMERIC,
    unrealized_pnl_pct    NUMERIC,
    max_favorable_excursion NUMERIC,
    max_adverse_excursion   NUMERIC,
    risk_flags_json       JSONB NOT NULL DEFAULT '[]'::jsonb,
    advice_label          TEXT,
    advice_reason         TEXT,
    quote_source          TEXT,              -- schwab_chain | broker_api | stale
    meta_json             JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_omps_position_at
    ON options_monitored_position_snapshots (position_id, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS options_monitored_alerts (
    id                    BIGSERIAL PRIMARY KEY,
    position_id           BIGINT NOT NULL REFERENCES options_monitored_positions(id) ON DELETE CASCADE,
    alert_type            TEXT NOT NULL,
    severity              TEXT NOT NULL DEFAULT 'warn',
    message               TEXT NOT NULL,
    broker                TEXT,
    execution_route       TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at       TIMESTAMPTZ,
    meta_json             JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_oma_position_unacked
    ON options_monitored_alerts (position_id, created_at DESC)
    WHERE acknowledged_at IS NULL;