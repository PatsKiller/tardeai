CREATE TABLE IF NOT EXISTS trade_llm_reviews (
    id BIGSERIAL PRIMARY KEY,
    paper_trade_id BIGINT, trace_id TEXT, proposal_id TEXT,
    symbol TEXT NOT NULL, strategy_id TEXT, account TEXT,
    review_stage TEXT NOT NULL, model_provider TEXT NOT NULL, model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL, input_snapshot_hash TEXT NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT now(), trade_close_date TIMESTAMPTZ,
    review_due_date TIMESTAMPTZ, status TEXT NOT NULL DEFAULT 'draft',
    summary TEXT, strengths JSONB, weaknesses JSONB,
    thesis_assessment TEXT, execution_assessment TEXT, stop_assessment TEXT,
    tca_assessment TEXT, post_close_assessment TEXT, backtest_comparison TEXT,
    lessons JSONB, confidence NUMERIC, data_quality_gaps JSONB,
    input_snapshot JSONB, output_payload JSONB, error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tlr_trade ON trade_llm_reviews(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_tlr_symbol ON trade_llm_reviews(symbol);
CREATE INDEX IF NOT EXISTS idx_tlr_stage ON trade_llm_reviews(review_stage);
CREATE INDEX IF NOT EXISTS idx_tlr_generated ON trade_llm_reviews(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tlr_hash ON trade_llm_reviews(input_snapshot_hash);

CREATE TABLE IF NOT EXISTS monthly_llm_meta_reviews (
    id BIGSERIAL PRIMARY KEY,
    review_month DATE NOT NULL, model_provider TEXT NOT NULL, model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL, generated_at TIMESTAMPTZ DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'draft', trade_count INTEGER DEFAULT 0,
    reviewed_trade_count INTEGER DEFAULT 0,
    patterns JSONB, strengths JSONB, weaknesses JSONB,
    strategy_lessons JSONB, behavioral_notes JSONB, recommendations JSONB,
    input_snapshot_hash TEXT, input_snapshot JSONB, output_payload JSONB,
    error_message TEXT, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mlmr_month ON monthly_llm_meta_reviews(review_month);
CREATE INDEX IF NOT EXISTS idx_mlmr_generated ON monthly_llm_meta_reviews(generated_at DESC);
