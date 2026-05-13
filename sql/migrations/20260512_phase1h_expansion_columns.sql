-- Phase 1H Expansion: columns and table for 5 new job types
-- Safe to run repeatedly (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)
-- Does NOT touch broker, holdings, execution, or trading behavior.

-- New result columns for specialized job types
ALTER TABLE deep_overnight_llm_results
    ADD COLUMN IF NOT EXISTS source_table       VARCHAR(60),
    ADD COLUMN IF NOT EXISTS source_id          INTEGER,
    ADD COLUMN IF NOT EXISTS curation_verdict   VARCHAR(30),
    ADD COLUMN IF NOT EXISTS curation_weight    DECIMAL(4,2),
    ADD COLUMN IF NOT EXISTS risk_narrative     TEXT,
    ADD COLUMN IF NOT EXISTS reentry_verdict    VARCHAR(30),
    ADD COLUMN IF NOT EXISTS cc_verdict         VARCHAR(20),
    ADD COLUMN IF NOT EXISTS cc_strike_target   DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS cc_yield_estimate  DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS behavioral_patterns JSONB;

-- Deep curation tracking on content source tables
ALTER TABLE news_articles
    ADD COLUMN IF NOT EXISTS deep_curation_verdict  VARCHAR(30),
    ADD COLUMN IF NOT EXISTS deep_curation_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deep_curation_weight   DECIMAL(4,2);

ALTER TABLE youtube_transcripts
    ADD COLUMN IF NOT EXISTS deep_curation_verdict  VARCHAR(30),
    ADD COLUMN IF NOT EXISTS deep_curation_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deep_curation_weight   DECIMAL(4,2);

-- Risk synthesis results table
CREATE TABLE IF NOT EXISTS risk_synthesis_results (
    id              SERIAL PRIMARY KEY,
    generated_at    TIMESTAMPTZ DEFAULT NOW(),
    portfolio_value DECIMAL(14,2),
    heat_pct        DECIMAL(5,2),
    top_risks       JSONB,
    narrative       TEXT,
    morning_brief_ready BOOLEAN DEFAULT FALSE,
    queue_id        INTEGER REFERENCES deep_overnight_llm_queue(id)
);

CREATE INDEX IF NOT EXISTS idx_risk_synthesis_generated
    ON risk_synthesis_results(generated_at DESC);

-- Source tracking index on queue for dedup
CREATE INDEX IF NOT EXISTS idx_dolq_source
    ON deep_overnight_llm_queue(source_table, source_id)
    WHERE source_table IS NOT NULL;
