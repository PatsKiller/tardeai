-- Agent Calibration Engine: Session 29
-- 2026-05-09 Idempotent: safe to re-run

-- A. Agent Recommendation Registry
CREATE TABLE IF NOT EXISTS agent_recommendation_registry (
    id                  BIGSERIAL PRIMARY KEY,
    recommendation_id   TEXT UNIQUE NOT NULL,
    agent_name          TEXT NOT NULL,
    agent_role          TEXT,
    source_table        TEXT,
    source_id           TEXT,
    symbol              TEXT,
    strategy_id         TEXT,
    recommendation_type TEXT NOT NULL,
    recommendation_action TEXT,
    confidence          NUMERIC,
    confidence_bucket   TEXT,
    time_horizon        TEXT,
    reasoning_summary   TEXT,
    evidence_refs       JSONB DEFAULT '[]'::jsonb,
    raw_payload         JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT now(),
    recommendation_time TIMESTAMPTZ,
    indexed_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_arr_agent ON agent_recommendation_registry(agent_name);
CREATE INDEX IF NOT EXISTS idx_arr_symbol ON agent_recommendation_registry(symbol);
CREATE INDEX IF NOT EXISTS idx_arr_time ON agent_recommendation_registry(recommendation_time);

-- B. Agent Recommendation Outcome Links
CREATE TABLE IF NOT EXISTS agent_recommendation_outcome_links (
    id                  BIGSERIAL PRIMARY KEY,
    link_id             TEXT UNIQUE NOT NULL,
    recommendation_id   TEXT NOT NULL,
    outcome_table       TEXT,
    outcome_id          TEXT,
    paper_trade_id      BIGINT,
    proposal_id         BIGINT,
    symbol              TEXT,
    strategy_id         TEXT,
    outcome_type        TEXT,
    link_confidence     NUMERIC DEFAULT 1.0,
    link_reason         TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_arol_rec ON agent_recommendation_outcome_links(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_arol_symbol ON agent_recommendation_outcome_links(symbol);

-- C. Agent Calibration Events
CREATE TABLE IF NOT EXISTS agent_calibration_events (
    id                      BIGSERIAL PRIMARY KEY,
    calibration_event_id    TEXT UNIQUE NOT NULL,
    recommendation_id       TEXT NOT NULL,
    agent_name              TEXT NOT NULL,
    symbol                  TEXT,
    strategy_id             TEXT,
    outcome_type            TEXT,
    scoring_window          TEXT,
    predicted_action        TEXT,
    predicted_confidence    NUMERIC,
    actual_outcome          TEXT,
    outcome_score           NUMERIC,
    pnl                     NUMERIC,
    pnl_pct                 NUMERIC,
    r_multiple              NUMERIC,
    price_move_pct          NUMERIC,
    calibration_error       NUMERIC,
    overconfidence          NUMERIC,
    underconfidence         NUMERIC,
    explanation             TEXT,
    evidence                JSONB DEFAULT '{}'::jsonb,
    low_sample_size         BOOLEAN DEFAULT true,
    created_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ace_agent ON agent_calibration_events(agent_name);
CREATE INDEX IF NOT EXISTS idx_ace_rec ON agent_calibration_events(recommendation_id);

-- D. Agent Calibration Windows
CREATE TABLE IF NOT EXISTS agent_calibration_windows (
    id                      BIGSERIAL PRIMARY KEY,
    window_id               TEXT UNIQUE NOT NULL,
    agent_name              TEXT NOT NULL,
    window_start            TIMESTAMPTZ NOT NULL,
    window_end              TIMESTAMPTZ NOT NULL,
    domain                  TEXT,
    strategy_id             TEXT,
    market_regime           TEXT,
    recommendations         INTEGER DEFAULT 0,
    resolved                INTEGER DEFAULT 0,
    correct                 INTEGER DEFAULT 0,
    incorrect               INTEGER DEFAULT 0,
    neutral                 INTEGER DEFAULT 0,
    partially_correct       INTEGER DEFAULT 0,
    unresolved              INTEGER DEFAULT 0,
    accuracy                NUMERIC,
    avg_confidence          NUMERIC,
    calibration_error       NUMERIC,
    brier_score             NUMERIC,
    overconfidence_score    NUMERIC,
    underconfidence_score   NUMERIC,
    avg_outcome_score       NUMERIC,
    avg_r_multiple          NUMERIC,
    win_rate                NUMERIC,
    profit_factor           NUMERIC,
    low_sample_size         BOOLEAN DEFAULT true,
    sample_size_status      TEXT,
    learning_summary        TEXT,
    recommendation          TEXT,
    payload                 JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ DEFAULT now(),
    UNIQUE(agent_name, window_start, window_end, domain, strategy_id)
);
CREATE INDEX IF NOT EXISTS idx_acw_agent ON agent_calibration_windows(agent_name);

-- E. Agent Weight Shadow Proposals
CREATE TABLE IF NOT EXISTS agent_weight_shadow_proposals (
    id                  BIGSERIAL PRIMARY KEY,
    shadow_proposal_id  TEXT UNIQUE NOT NULL,
    recommendation_id   TEXT,
    agent_name          TEXT NOT NULL,
    domain              TEXT,
    strategy_id         TEXT,
    current_weight      NUMERIC,
    proposed_weight     NUMERIC,
    weight_delta        NUMERIC,
    reason              TEXT,
    evidence            JSONB DEFAULT '{}'::jsonb,
    sample_size         INTEGER DEFAULT 0,
    confidence          NUMERIC,
    risk_level          TEXT DEFAULT 'medium',
    status              TEXT DEFAULT 'proposed',
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_awsp_agent ON agent_weight_shadow_proposals(agent_name);
CREATE INDEX IF NOT EXISTS idx_awsp_status ON agent_weight_shadow_proposals(status);

-- F. Agent Disagreement Outcomes
CREATE TABLE IF NOT EXISTS agent_disagreement_outcomes (
    id                  BIGSERIAL PRIMARY KEY,
    disagreement_id     TEXT UNIQUE NOT NULL,
    symbol              TEXT,
    strategy_id         TEXT,
    source_table        TEXT,
    source_id           TEXT,
    agents_involved     JSONB NOT NULL DEFAULT '[]'::jsonb,
    disagreement_type   TEXT,
    winning_view        TEXT,
    losing_view         TEXT,
    outcome_summary     TEXT,
    outcome_score       JSONB DEFAULT '{}'::jsonb,
    resolved            BOOLEAN DEFAULT false,
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- G. Agent Calibration Run Log
CREATE TABLE IF NOT EXISTS agent_calibration_run_log (
    id                          BIGSERIAL PRIMARY KEY,
    run_id                      TEXT UNIQUE NOT NULL,
    mode                        TEXT,
    started_at                  TIMESTAMPTZ DEFAULT now(),
    finished_at                 TIMESTAMPTZ,
    status                      TEXT DEFAULT 'running',
    recommendations_indexed     INTEGER DEFAULT 0,
    outcome_links_created       INTEGER DEFAULT 0,
    calibration_events_created  INTEGER DEFAULT 0,
    windows_updated             INTEGER DEFAULT 0,
    learning_evidence_created   INTEGER DEFAULT 0,
    recommendations_created     INTEGER DEFAULT 0,
    errors                      JSONB DEFAULT '[]'::jsonb,
    summary                     JSONB DEFAULT '{}'::jsonb
);
