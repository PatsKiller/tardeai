-- 017_v5_proactive_intelligence.sql — V5: Remaining signal tables
-- Idempotent.
BEGIN;

CREATE TABLE IF NOT EXISTS sentiment_observations (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    strategy_type       TEXT,
    source_type         TEXT,
    source_id           BIGINT,
    overall_sentiment   TEXT,
    sentiment_score     NUMERIC,
    confidence          NUMERIC,
    key_phrases         JSONB DEFAULT '[]'::jsonb,
    risk_keywords       JSONB DEFAULT '[]'::jsonb,
    opportunity_keywords JSONB DEFAULT '[]'::jsonb,
    model_used          TEXT,
    raw_text_snippet    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sentiment_symbol ON sentiment_observations (symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS signal_clusters (
    id                  BIGSERIAL PRIMARY KEY,
    cluster_date        DATE NOT NULL,
    strategy_type       TEXT,
    group_id            TEXT,
    cluster_type        TEXT,
    symbols_involved    TEXT[],
    signal_count        INTEGER,
    avg_severity        NUMERIC,
    dominant_direction  TEXT,
    portfolio_impact    NUMERIC,
    requires_action     BOOLEAN DEFAULT FALSE,
    summary             TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cluster_date ON signal_clusters (cluster_date DESC);

COMMIT;
