-- Risk Regime + Strategy Rotation Signals: Session 33
-- 2026-05-09 Idempotent

CREATE TABLE IF NOT EXISTS market_regime_snapshots (
    id BIGSERIAL PRIMARY KEY, snapshot_id TEXT UNIQUE NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT now(), market_session TEXT,
    regime_label TEXT NOT NULL, regime_score NUMERIC, confidence NUMERIC,
    volatility_state TEXT, trend_state TEXT, breadth_state TEXT,
    liquidity_state TEXT, leadership_state TEXT, risk_appetite_state TEXT,
    macro_state TEXT, data_freshness_state TEXT,
    stale_data BOOLEAN DEFAULT false, missing_data JSONB DEFAULT '[]'::jsonb,
    inputs JSONB DEFAULT '{}'::jsonb, summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mrs_regime ON market_regime_snapshots(regime_label);

CREATE TABLE IF NOT EXISTS market_regime_indicators (
    id BIGSERIAL PRIMARY KEY, indicator_id TEXT UNIQUE NOT NULL,
    snapshot_id TEXT, indicator_key TEXT NOT NULL,
    indicator_group TEXT, value NUMERIC, value_text TEXT,
    signal TEXT, weight NUMERIC DEFAULT 1.0,
    freshness_seconds NUMERIC, source_key TEXT,
    payload JSONB DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mri_snapshot ON market_regime_indicators(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_mri_key ON market_regime_indicators(indicator_key);

CREATE TABLE IF NOT EXISTS strategy_regime_profiles (
    id BIGSERIAL PRIMARY KEY, profile_id TEXT UNIQUE NOT NULL,
    strategy_id TEXT NOT NULL UNIQUE, strategy_name TEXT,
    favored_regimes JSONB DEFAULT '[]'::jsonb,
    disfavored_regimes JSONB DEFAULT '[]'::jsonb,
    neutral_regimes JSONB DEFAULT '[]'::jsonb,
    volatility_preference TEXT, trend_preference TEXT,
    liquidity_requirement TEXT, breadth_requirement TEXT,
    time_horizon TEXT, risk_notes TEXT,
    source TEXT DEFAULT 'session33_seed', active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy_rotation_signals (
    id BIGSERIAL PRIMARY KEY, signal_id TEXT UNIQUE NOT NULL,
    snapshot_id TEXT, strategy_id TEXT NOT NULL, strategy_name TEXT,
    signal TEXT NOT NULL, signal_strength NUMERIC, confidence NUMERIC,
    reason TEXT, supporting_indicators JSONB DEFAULT '[]'::jsonb,
    conflicting_indicators JSONB DEFAULT '[]'::jsonb,
    current_strategy_status TEXT, recommended_action TEXT,
    requires_admin_approval BOOLEAN DEFAULT true,
    learning_hypothesis_id TEXT, learning_recommendation_id TEXT,
    config_proposal_id TEXT, status TEXT DEFAULT 'open',
    created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_srs_strategy ON strategy_rotation_signals(strategy_id);
CREATE INDEX IF NOT EXISTS idx_srs_signal ON strategy_rotation_signals(signal);

CREATE TABLE IF NOT EXISTS regime_trade_alignment (
    id BIGSERIAL PRIMARY KEY, alignment_id TEXT UNIQUE NOT NULL,
    snapshot_id TEXT, symbol TEXT, strategy_id TEXT,
    paper_trade_id BIGINT, proposal_id BIGINT,
    alignment_type TEXT, alignment_score NUMERIC,
    alignment_label TEXT, regime_label TEXT, reason TEXT,
    risk_flags JSONB DEFAULT '[]'::jsonb, recommended_review TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rta_symbol ON regime_trade_alignment(symbol);

CREATE TABLE IF NOT EXISTS regime_learning_evidence_links (
    id BIGSERIAL PRIMARY KEY, link_id TEXT UNIQUE NOT NULL,
    snapshot_id TEXT, signal_id TEXT, alignment_id TEXT,
    evidence_id TEXT, hypothesis_id TEXT, recommendation_id TEXT,
    proposal_id TEXT, link_type TEXT, link_confidence NUMERIC DEFAULT 1.0,
    payload JSONB DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS risk_regime_run_log (
    id BIGSERIAL PRIMARY KEY, run_id TEXT UNIQUE NOT NULL,
    mode TEXT, started_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ, status TEXT DEFAULT 'running',
    indicators_read INTEGER DEFAULT 0, snapshots_created INTEGER DEFAULT 0,
    rotation_signals_created INTEGER DEFAULT 0,
    alignments_created INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]'::jsonb, summary JSONB DEFAULT '{}'::jsonb
);
