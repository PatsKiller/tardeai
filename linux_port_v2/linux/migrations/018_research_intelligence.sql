-- 018_research_intelligence.sql — V6B: Research Intelligence + Calibration
-- Idempotent.
BEGIN;

-- 1. Research sources (YouTube channels, newsletters, blogs, etc.)
CREATE TABLE IF NOT EXISTS research_sources (
    id                  BIGSERIAL PRIMARY KEY,
    source_type         TEXT NOT NULL,  -- youtube, newsletter, blog, podcast, analyst_report
    source_name         TEXT NOT NULL,
    source_url          TEXT,
    credibility_score   NUMERIC DEFAULT 0.5,
    specialty           TEXT[],         -- strategy types this source is good for
    active              BOOLEAN DEFAULT TRUE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Research insights — structured decision-ready data from research
CREATE TABLE IF NOT EXISTS research_insights (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    strategy_type       TEXT,
    source_id           BIGINT REFERENCES research_sources(id),
    source_type         TEXT,
    source_reference    TEXT,           -- URL or transcript ID
    thesis_type         TEXT NOT NULL CHECK (thesis_type IN ('bullish','bearish','neutral','mixed')),
    time_horizon        TEXT CHECK (time_horizon IN ('short','medium','long')),
    confidence          NUMERIC DEFAULT 0.5,
    headline            TEXT,
    structured_thesis   TEXT,           -- 1-2 sentence structured summary
    supporting_entities TEXT[],         -- tickers, sectors, themes mentioned
    key_arguments       JSONB DEFAULT '[]'::jsonb,
    contradiction_flags JSONB DEFAULT '[]'::jsonb,
    price_target        NUMERIC,
    yield_thesis        TEXT,           -- for income-relevant insights
    risk_factors        JSONB DEFAULT '[]'::jsonb,
    raw_text            TEXT,
    extraction_model    TEXT,
    extraction_confidence NUMERIC,
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_research_symbol ON research_insights (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_thesis ON research_insights (thesis_type, strategy_type);

-- 3. Confidence calibration history
CREATE TABLE IF NOT EXISTS confidence_calibration_history (
    id                  BIGSERIAL PRIMARY KEY,
    calibration_date    DATE NOT NULL,
    scope               TEXT NOT NULL,  -- 'global', strategy_type, agent name, signal source
    scope_value         TEXT,
    predicted_confidence NUMERIC,
    actual_accuracy     NUMERIC,
    calibration_error   NUMERIC,
    sample_size         INTEGER,
    recommendation      TEXT,           -- 'increase', 'decrease', 'maintain'
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Add research_score to fused_signals if not exists
ALTER TABLE fused_signals
    ADD COLUMN IF NOT EXISTS research_score NUMERIC DEFAULT 0,
    ADD COLUMN IF NOT EXISTS research_insight_ids BIGINT[];

-- 5. Add research_contribution to decision_outcomes if not exists
ALTER TABLE decision_outcomes
    ADD COLUMN IF NOT EXISTS research_influence NUMERIC DEFAULT 0,
    ADD COLUMN IF NOT EXISTS research_insight_ids BIGINT[];

COMMIT;
