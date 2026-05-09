-- Discovery Source Health + Paper Validation Gate + System Facts
-- 2026-05-09 Hardening Sprint Workstreams C, D, E

-- Workstream C: Source health tracking
CREATE TABLE IF NOT EXISTS data_source_health (
    id                  BIGSERIAL PRIMARY KEY,
    source_key          TEXT UNIQUE NOT NULL,
    status              TEXT NOT NULL DEFAULT 'unknown',
    last_success_at     TIMESTAMPTZ,
    last_failure_at     TIMESTAMPTZ,
    last_row_count      INTEGER,
    failure_count       INTEGER DEFAULT 0,
    last_error          TEXT,
    degraded            BOOLEAN DEFAULT false,
    max_stale_minutes   INTEGER DEFAULT 1440,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS candidate_discovery_events (
    id                  BIGSERIAL PRIMARY KEY,
    event_id            TEXT UNIQUE NOT NULL,
    source_key          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    discovered_at       TIMESTAMPTZ DEFAULT NOW(),
    source_confidence   NUMERIC,
    raw_payload         JSONB,
    normalized_payload  JSONB,
    degraded            BOOLEAN DEFAULT false,
    reason              TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed known sources
INSERT INTO data_source_health (source_key, status, max_stale_minutes) VALUES
    ('finviz', 'unknown', 360),
    ('yahoo_finance', 'unknown', 1440),
    ('polygon', 'unknown', 1440),
    ('newsapi', 'unknown', 720),
    ('finnhub', 'unknown', 720),
    ('fmp', 'unknown', 1440),
    ('alpha_vantage', 'unknown', 1440),
    ('fred', 'unknown', 1440),
    ('sec_edgar', 'unknown', 1440),
    ('youtube_api', 'unknown', 1440),
    ('brave_search', 'unknown', 1440),
    ('incubator', 'unknown', 1440),
    ('news_catalyst', 'unknown', 720)
ON CONFLICT (source_key) DO NOTHING;

-- Workstream D: Paper validation gate
CREATE TABLE IF NOT EXISTS paper_validation_policy (
    id                          BIGSERIAL PRIMARY KEY,
    policy_key                  TEXT UNIQUE NOT NULL,
    active                      BOOLEAN DEFAULT true,
    validation_start_date       DATE,
    minimum_validation_days     INTEGER DEFAULT 183,
    minimum_closed_trades       INTEGER DEFAULT 100,
    minimum_win_rate            NUMERIC DEFAULT 0.55,
    minimum_profit_factor       NUMERIC DEFAULT 1.30,
    requires_governance_approval BOOLEAN DEFAULT true,
    live_trading_allowed        BOOLEAN DEFAULT false,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_validation_daily_metrics (
    id                  BIGSERIAL PRIMARY KEY,
    metric_date         DATE UNIQUE NOT NULL,
    closed_trades       INTEGER DEFAULT 0,
    wins                INTEGER DEFAULT 0,
    losses              INTEGER DEFAULT 0,
    win_rate            NUMERIC,
    gross_profit        NUMERIC,
    gross_loss          NUMERIC,
    profit_factor       NUMERIC,
    max_drawdown        NUMERIC,
    open_paper_trades   INTEGER,
    generated_at        TIMESTAMPTZ DEFAULT NOW(),
    payload             JSONB
);

CREATE TABLE IF NOT EXISTS governance_approvals (
    id              BIGSERIAL PRIMARY KEY,
    approval_key    TEXT UNIQUE NOT NULL,
    approval_type   TEXT NOT NULL,
    approved        BOOLEAN DEFAULT false,
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    rationale       TEXT,
    payload         JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Seed paper validation policy
INSERT INTO paper_validation_policy
    (policy_key, active, validation_start_date, minimum_validation_days,
     minimum_closed_trades, minimum_win_rate, minimum_profit_factor,
     requires_governance_approval, live_trading_allowed, notes)
VALUES
    ('live_trading_gate_v1', true, '2026-05-08', 183, 100, 0.55, 1.30,
     true, false, 'Paper validation window. Live trading blocked until all gates pass.')
ON CONFLICT (policy_key) DO NOTHING;

-- Workstream E: System facts history
CREATE TABLE IF NOT EXISTS system_facts_history (
    id              BIGSERIAL PRIMARY KEY,
    generated_at    TIMESTAMPTZ DEFAULT NOW(),
    facts           JSONB NOT NULL,
    drift           JSONB,
    checksum        TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_health_key ON data_source_health(source_key);
CREATE INDEX IF NOT EXISTS idx_discovery_events_sym ON candidate_discovery_events(symbol, discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_facts_history ON system_facts_history(generated_at DESC);
