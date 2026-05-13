-- Two-tier rebalance advisor: gemma3 monthly deep + Sonnet weekly verification
-- Safe to run repeatedly (IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS rebalance_analysis_results (
    id                      SERIAL PRIMARY KEY,
    generated_at            TIMESTAMPTZ DEFAULT NOW(),
    analysis_tier           VARCHAR(20) NOT NULL,
    portfolio_value         DECIMAL(14,2),
    yaml_health_score       INTEGER,
    holdings_snapshot       JSONB,
    executive_summary       TEXT,
    recommendations         JSONB,
    v_concentration_plan    TEXT,
    bond_ballast_assessment TEXT,
    yaml_gaps               JSONB,
    ssdi_irmaa_flags        JSONB,
    verification_passed     BOOLEAN,
    verification_notes      TEXT,
    verified_at             TIMESTAMPTZ,
    model_primary           VARCHAR(40),
    model_verifier          VARCHAR(40),
    prompt_version          VARCHAR(10) DEFAULT 'v1',
    stale_days_at_run       INTEGER,
    queue_id                INTEGER REFERENCES deep_overnight_llm_queue(id)
);

CREATE INDEX IF NOT EXISTS idx_rebalance_analysis_generated
    ON rebalance_analysis_results(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_rebalance_analysis_tier
    ON rebalance_analysis_results(analysis_tier, generated_at DESC);
