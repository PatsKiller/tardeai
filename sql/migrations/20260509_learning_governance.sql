-- Learning Governance: Self-improvement control plane
-- 2026-05-09 Session 28
-- Idempotent: safe to re-run

-- A. Learning Hypotheses
CREATE TABLE IF NOT EXISTS learning_hypotheses (
    id              BIGSERIAL PRIMARY KEY,
    hypothesis_id   TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    domain          TEXT NOT NULL,
    hypothesis_type TEXT NOT NULL,
    description     TEXT,
    generated_by    TEXT DEFAULT 'system',
    source_table    TEXT,
    source_id       TEXT,
    symbol          TEXT,
    strategy_id     TEXT,
    agent_name      TEXT,
    status          TEXT DEFAULT 'draft',
    sample_size     INTEGER DEFAULT 0,
    confidence      NUMERIC,
    expected_impact TEXT,
    risk_level      TEXT DEFAULT 'medium',
    payload         JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lh_status ON learning_hypotheses(status);
CREATE INDEX IF NOT EXISTS idx_lh_domain ON learning_hypotheses(domain);

-- B. Learning Experiments
CREATE TABLE IF NOT EXISTS learning_experiments (
    id                  BIGSERIAL PRIMARY KEY,
    experiment_id       TEXT UNIQUE NOT NULL,
    hypothesis_id       TEXT REFERENCES learning_hypotheses(hypothesis_id),
    name                TEXT NOT NULL,
    domain              TEXT NOT NULL,
    experiment_type     TEXT NOT NULL,
    status              TEXT DEFAULT 'planned',
    champion_config     JSONB,
    challenger_config   JSONB,
    start_at            TIMESTAMPTZ,
    end_at              TIMESTAMPTZ,
    min_sample_size     INTEGER DEFAULT 30,
    actual_sample_size  INTEGER DEFAULT 0,
    metrics             JSONB DEFAULT '{}'::jsonb,
    result_summary      TEXT,
    conclusion          TEXT,
    recommended_action  TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_le_status ON learning_experiments(status);
CREATE INDEX IF NOT EXISTS idx_le_hypothesis ON learning_experiments(hypothesis_id);

-- C. Learning Evidence
CREATE TABLE IF NOT EXISTS learning_evidence (
    id                  BIGSERIAL PRIMARY KEY,
    evidence_id         TEXT UNIQUE NOT NULL,
    hypothesis_id       TEXT REFERENCES learning_hypotheses(hypothesis_id),
    experiment_id       TEXT,
    evidence_type       TEXT NOT NULL,
    source_table        TEXT,
    source_id           TEXT,
    symbol              TEXT,
    strategy_id         TEXT,
    agent_name          TEXT,
    supports_hypothesis BOOLEAN,
    weight              NUMERIC DEFAULT 1.0,
    quality_score       NUMERIC,
    evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lev_hypothesis ON learning_evidence(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_lev_type ON learning_evidence(evidence_type);

-- D. Learning Recommendations
CREATE TABLE IF NOT EXISTS learning_recommendations (
    id                      BIGSERIAL PRIMARY KEY,
    recommendation_id       TEXT UNIQUE NOT NULL,
    hypothesis_id           TEXT REFERENCES learning_hypotheses(hypothesis_id),
    experiment_id           TEXT,
    domain                  TEXT NOT NULL,
    recommendation_type     TEXT NOT NULL,
    title                   TEXT NOT NULL,
    summary                 TEXT,
    evidence_summary        JSONB DEFAULT '{}'::jsonb,
    sample_size             INTEGER DEFAULT 0,
    confidence              NUMERIC,
    expected_benefit        TEXT,
    risk_level              TEXT,
    status                  TEXT DEFAULT 'proposed',
    requires_admin_approval BOOLEAN DEFAULT true,
    created_by              TEXT DEFAULT 'learning_engine',
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lr_status ON learning_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_lr_domain ON learning_recommendations(domain);

-- E. Config Change Proposals
CREATE TABLE IF NOT EXISTS config_change_proposals (
    id              BIGSERIAL PRIMARY KEY,
    proposal_id     TEXT UNIQUE NOT NULL,
    recommendation_id TEXT,
    domain          TEXT NOT NULL,
    target_key      TEXT NOT NULL,
    target_table    TEXT,
    target_path     TEXT,
    change_type     TEXT NOT NULL,
    current_config  JSONB,
    proposed_config JSONB,
    diff            JSONB,
    reason          TEXT,
    evidence        JSONB DEFAULT '{}'::jsonb,
    risk_assessment TEXT,
    rollback_plan   TEXT,
    status          TEXT DEFAULT 'proposed',
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    implemented_by  TEXT,
    implemented_at  TIMESTAMPTZ,
    rejected_at     TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ccp_status ON config_change_proposals(status);
CREATE INDEX IF NOT EXISTS idx_ccp_domain ON config_change_proposals(domain);

-- F. Learning Promotion Decisions
CREATE TABLE IF NOT EXISTS learning_promotion_decisions (
    id               BIGSERIAL PRIMARY KEY,
    decision_id      TEXT UNIQUE NOT NULL,
    proposal_id      TEXT,
    recommendation_id TEXT,
    hypothesis_id    TEXT,
    decision         TEXT NOT NULL,
    decided_by       TEXT NOT NULL,
    rationale        TEXT,
    decision_payload JSONB DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ DEFAULT now()
);

-- G. Learning Rollback Events
CREATE TABLE IF NOT EXISTS learning_rollback_events (
    id              BIGSERIAL PRIMARY KEY,
    rollback_id     TEXT UNIQUE NOT NULL,
    proposal_id     TEXT,
    domain          TEXT,
    target_key      TEXT,
    rollback_reason TEXT,
    prior_config    JSONB,
    rollback_config JSONB,
    rollback_status TEXT DEFAULT 'proposed',
    executed_by     TEXT,
    executed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- H. Source Learning Scores
CREATE TABLE IF NOT EXISTS source_learning_scores (
    id                  BIGSERIAL PRIMARY KEY,
    source_key          TEXT NOT NULL,
    window_start        TIMESTAMPTZ,
    window_end          TIMESTAMPTZ,
    signals_seen        INTEGER DEFAULT 0,
    unique_symbols      INTEGER DEFAULT 0,
    duplicates          INTEGER DEFAULT 0,
    stale_items         INTEGER DEFAULT 0,
    false_catalysts     INTEGER DEFAULT 0,
    candidates_promoted INTEGER DEFAULT 0,
    paper_trades_created INTEGER DEFAULT 0,
    closed_trades       INTEGER DEFAULT 0,
    winning_trades      INTEGER DEFAULT 0,
    losing_trades       INTEGER DEFAULT 0,
    avg_r_multiple      NUMERIC,
    profit_factor       NUMERIC,
    usefulness_score    NUMERIC,
    reliability_score   NUMERIC,
    cost_estimate       NUMERIC,
    recommendation      TEXT,
    payload             JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE(source_key, window_start, window_end)
);

-- I. Strategy Learning Scores
CREATE TABLE IF NOT EXISTS strategy_learning_scores (
    id                  BIGSERIAL PRIMARY KEY,
    strategy_id         TEXT NOT NULL,
    window_start        TIMESTAMPTZ,
    window_end          TIMESTAMPTZ,
    proposals           INTEGER DEFAULT 0,
    approved            INTEGER DEFAULT 0,
    paper_trades        INTEGER DEFAULT 0,
    closed_trades       INTEGER DEFAULT 0,
    wins                INTEGER DEFAULT 0,
    losses              INTEGER DEFAULT 0,
    win_rate            NUMERIC,
    profit_factor       NUMERIC,
    expectancy_r        NUMERIC,
    avg_slippage_bps    NUMERIC,
    avg_hold_minutes    NUMERIC,
    stop_hit_rate       NUMERIC,
    target_hit_rate     NUMERIC,
    low_sample_size     BOOLEAN DEFAULT true,
    learning_summary    TEXT,
    recommendation      TEXT,
    payload             JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE(strategy_id, window_start, window_end)
);

-- J. Agent Learning Scores
CREATE TABLE IF NOT EXISTS agent_learning_scores (
    id                      BIGSERIAL PRIMARY KEY,
    agent_name              TEXT NOT NULL,
    window_start            TIMESTAMPTZ,
    window_end              TIMESTAMPTZ,
    recommendations         INTEGER DEFAULT 0,
    correct                 INTEGER DEFAULT 0,
    incorrect               INTEGER DEFAULT 0,
    neutral                 INTEGER DEFAULT 0,
    accuracy                NUMERIC,
    avg_confidence          NUMERIC,
    calibration_error       NUMERIC,
    overconfidence_score    NUMERIC,
    underconfidence_score   NUMERIC,
    best_strategy           TEXT,
    worst_strategy          TEXT,
    learning_summary        TEXT,
    recommendation          TEXT,
    payload                 JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ DEFAULT now(),
    UNIQUE(agent_name, window_start, window_end)
);
