-- Session 11: Prop Desk Governance + Strategy Skill Layer
-- Additive migration only — no drops, truncates, or renames.
-- Run: psql -h 127.0.0.1 -U trade_ai -d trade_ai -f sql/migrations/20260505_1800_session11_prop_desk_governance.sql

BEGIN;

-- ══════════════════════════════════════════════════════
-- audit_log — immutable decision/action log
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audit_log (
    id                  SERIAL PRIMARY KEY,
    event_type          TEXT NOT NULL,
    strategy_id         TEXT,
    symbol              TEXT,
    account             TEXT,
    decision            TEXT,
    reason_codes        JSONB,
    reason_text         TEXT,
    input_snapshot      JSONB,
    mode                TEXT,
    actor               TEXT DEFAULT 'system',
    model_used          TEXT,
    confidence          NUMERIC,
    signal_id           INTEGER,
    trade_id            INTEGER,
    strategy_signal_id  INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_type     ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_symbol   ON audit_log(symbol);
CREATE INDEX IF NOT EXISTS idx_audit_log_strategy ON audit_log(strategy_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created  ON audit_log(created_at DESC);

-- ══════════════════════════════════════════════════════
-- risk_gate_results — fast-query risk decision log
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS risk_gate_results (
    id              SERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    strategy_id     TEXT,
    account         TEXT,
    mode            TEXT,
    action_context  TEXT,
    result          TEXT NOT NULL,
    approved        BOOLEAN NOT NULL DEFAULT false,
    reason_codes    JSONB,
    reason_text     TEXT,
    input_snapshot  JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rgr_symbol  ON risk_gate_results(symbol);
CREATE INDEX IF NOT EXISTS idx_rgr_created ON risk_gate_results(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rgr_result  ON risk_gate_results(result);

-- ══════════════════════════════════════════════════════
-- paper_trades — full paper trade lifecycle
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS paper_trades (
    id                      SERIAL PRIMARY KEY,
    signal_id               INTEGER,
    strategy_id             TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    account                 TEXT NOT NULL,
    entry_price             NUMERIC,
    entry_time              TIMESTAMPTZ,
    shares                  INTEGER,
    dollar_size             NUMERIC,
    stop_loss               NUMERIC,
    target_1                NUMERIC,
    target_2                NUMERIC,
    dollar_risk             NUMERIC DEFAULT 150,
    score_at_entry          INTEGER,
    rvol_at_entry           NUMERIC,
    float_m_at_entry        NUMERIC,
    catalyst_at_entry       TEXT,
    catalyst_verified       BOOLEAN,
    intel_readiness          INTEGER,
    vix_at_entry            NUMERIC,
    market_regime           TEXT,
    trade_plan_id           INTEGER,
    exit_price              NUMERIC,
    exit_time               TIMESTAMPTZ,
    exit_reason             TEXT,
    pnl                     NUMERIC,
    pnl_pct                 NUMERIC,
    hold_time_min           INTEGER,
    planned_entry           NUMERIC,
    entry_slippage          NUMERIC,
    planned_stop            NUMERIC,
    stop_slippage           NUMERIC,
    max_adverse_excursion   NUMERIC,
    max_favorable_excursion NUMERIC,
    outcome_verdict         TEXT,
    status                  TEXT DEFAULT 'open',
    logged_by               TEXT DEFAULT 'system',
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    closed_at               TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pt_strategy ON paper_trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_pt_symbol   ON paper_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_pt_status   ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_pt_created  ON paper_trades(created_at DESC);

-- ══════════════════════════════════════════════════════
-- strategy_cards — normalized strategy card outputs
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS strategy_cards (
    id                          SERIAL PRIMARY KEY,
    symbol                      TEXT NOT NULL,
    strategy_id                 TEXT NOT NULL,
    setup_type                  TEXT,
    grade                       TEXT,
    score                       NUMERIC,
    confidence                  NUMERIC,
    data_quality_score          INTEGER,
    source_quality_score        NUMERIC,
    recommendation              TEXT,
    recommendation_reason       TEXT,
    entry_zone                  JSONB,
    stop                        NUMERIC,
    target_1                    NUMERIC,
    target_2                    NUMERIC,
    risk_reward                 NUMERIC,
    shares                      INTEGER,
    dollar_risk                 NUMERIC,
    risk_gate_result            TEXT,
    risk_gate_reason_codes      JSONB,
    required_evidence_present   BOOLEAN,
    missing_evidence            JSONB,
    disqualifiers               JSONB,
    agent_votes                 JSONB,
    account_fit                 TEXT,
    vix_at_signal               NUMERIC,
    market_regime               TEXT,
    sector_rank                 INTEGER,
    intel_readiness             INTEGER,
    final_action                TEXT,
    explanation                 TEXT,
    what_would_change_decision  TEXT,
    source_payload              JSONB,
    generated_by                TEXT DEFAULT 'system',
    parameter_version           TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sc_symbol   ON strategy_cards(symbol);
CREATE INDEX IF NOT EXISTS idx_sc_strategy ON strategy_cards(strategy_id);
CREATE INDEX IF NOT EXISTS idx_sc_created  ON strategy_cards(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sc_grade    ON strategy_cards(grade);

-- ══════════════════════════════════════════════════════
-- system_controls — halt flags and global controls
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS system_controls (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_by  TEXT DEFAULT 'system'
);

INSERT INTO system_controls (key, value) VALUES
    ('halt_all_trading', 'false'),
    ('halt_live_only', 'false'),
    ('halt_momentum_scalp_strategy', 'false'),
    ('halt_gap_and_go_strategy', 'false'),
    ('halt_swing_breakout_strategy', 'false'),
    ('halt_sector_rotation_strategy', 'false'),
    ('halt_earnings_catalyst_strategy', 'false'),
    ('halt_income_add_strategy', 'false')
ON CONFLICT (key) DO NOTHING;

-- ══════════════════════════════════════════════════════
-- strategy_parameter_versions — YAML version tracking
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS strategy_parameter_versions (
    id              SERIAL PRIMARY KEY,
    strategy_id     TEXT NOT NULL,
    version         TEXT NOT NULL,
    parameters      JSONB NOT NULL,
    changed_by      TEXT DEFAULT 'system',
    change_reason   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spv_strategy ON strategy_parameter_versions(strategy_id);

-- ══════════════════════════════════════════════════════
-- strategy_state_transitions — lifecycle change log
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS strategy_state_transitions (
    id              SERIAL PRIMARY KEY,
    strategy_id     TEXT NOT NULL,
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    reason          TEXT,
    metrics         JSONB,
    decided_by      TEXT DEFAULT 'system',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sst_strategy ON strategy_state_transitions(strategy_id);

-- ══════════════════════════════════════════════════════
-- pattern_library — proven/killed patterns
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pattern_library (
    id              SERIAL PRIMARY KEY,
    pattern_name    TEXT NOT NULL,
    strategy_id     TEXT,
    definition      JSONB NOT NULL,
    status          TEXT DEFAULT 'CANDIDATE',
    trade_count     INTEGER DEFAULT 0,
    win_rate        NUMERIC,
    avg_winner      NUMERIC,
    avg_loser       NUMERIC,
    expectancy      NUMERIC,
    profit_factor   NUMERIC,
    scoring_bonus   JSONB,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pl_strategy ON pattern_library(strategy_id);
CREATE INDEX IF NOT EXISTS idx_pl_status   ON pattern_library(status);

-- ══════════════════════════════════════════════════════
-- Add strategy_signals and trade_plans if not exist
-- (may have been created in Session 10)
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS strategy_signals (
    id                  SERIAL PRIMARY KEY,
    strategy_id         TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    signal_type         TEXT NOT NULL DEFAULT 'LONG',
    signal_grade        TEXT,
    signal_score        NUMERIC,
    price               NUMERIC,
    rvol                NUMERIC,
    float_m             NUMERIC,
    gap_pct             NUMERIC,
    catalyst            TEXT,
    catalyst_verified   BOOLEAN DEFAULT false,
    setup_description   TEXT,
    entry_low           NUMERIC,
    entry_high          NUMERIC,
    stop_loss           NUMERIC,
    target_1            NUMERIC,
    target_2            NUMERIC,
    risk_reward         NUMERIC,
    shares              INTEGER,
    dollar_risk         NUMERIC,
    vix_at_signal       NUMERIC,
    market_regime       TEXT,
    sector              TEXT,
    intel_readiness     INTEGER,
    source_quality      NUMERIC,
    status              TEXT DEFAULT 'active',
    fired_at            TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,
    telegram_sent       BOOLEAN DEFAULT false,
    trade_journal_id    INTEGER,
    outcome_verdict     TEXT,
    outcome_pnl         NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_ss_strategy ON strategy_signals(strategy_id);
CREATE INDEX IF NOT EXISTS idx_ss_symbol   ON strategy_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_ss_fired    ON strategy_signals(fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_ss_status   ON strategy_signals(status);

CREATE TABLE IF NOT EXISTS trade_plans (
    id                  SERIAL PRIMARY KEY,
    signal_id           INTEGER,
    strategy_id         TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    entry_low           NUMERIC NOT NULL,
    entry_high          NUMERIC NOT NULL,
    stop_loss           NUMERIC NOT NULL,
    stop_pct            NUMERIC NOT NULL,
    target_1            NUMERIC NOT NULL,
    target_2            NUMERIC,
    risk_reward_1       NUMERIC,
    risk_reward_2       NUMERIC,
    shares              INTEGER NOT NULL,
    dollar_size         NUMERIC NOT NULL,
    dollar_risk         NUMERIC NOT NULL DEFAULT 150,
    atr_value           NUMERIC,
    atr_multiplier      NUMERIC DEFAULT 1.5,
    disqualified        BOOLEAN DEFAULT false,
    disqualify_reason   TEXT,
    tos_order_string    TEXT,
    generated_at        TIMESTAMPTZ DEFAULT NOW(),
    generated_by        TEXT DEFAULT 'trade_plan_engine'
);

CREATE INDEX IF NOT EXISTS idx_tp_symbol    ON trade_plans(symbol);
CREATE INDEX IF NOT EXISTS idx_tp_generated ON trade_plans(generated_at DESC);

COMMIT;
