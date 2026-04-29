-- 016_signal_intelligence_tables.sql — V4: Signal Intelligence Pipeline
-- Idempotent.
BEGIN;

-- 1. Catalyst events
CREATE TABLE IF NOT EXISTS catalyst_events (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    strategy_type       TEXT,
    catalyst_type       TEXT NOT NULL,
    headline            TEXT,
    description         TEXT,
    severity            TEXT DEFAULT 'medium',
    confidence          NUMERIC DEFAULT 0.5,
    impact_score        NUMERIC,
    source              TEXT,
    source_url          TEXT,
    raw_payload         JSONB DEFAULT '{}'::jsonb,
    published_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_catalyst_symbol ON catalyst_events (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_catalyst_type ON catalyst_events (catalyst_type, severity);

-- 2. Catalyst symbol impact (linking catalysts to portfolio impact)
CREATE TABLE IF NOT EXISTS catalyst_symbol_impact (
    id                  BIGSERIAL PRIMARY KEY,
    catalyst_event_id   BIGINT REFERENCES catalyst_events(id),
    symbol              TEXT NOT NULL,
    strategy_type       TEXT,
    price_at_event      NUMERIC,
    expected_direction  TEXT,
    expected_magnitude  TEXT,
    portfolio_impact_pct NUMERIC,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Portfolio catalyst summary (daily roll-up)
CREATE TABLE IF NOT EXISTS portfolio_catalyst_summary (
    id                  BIGSERIAL PRIMARY KEY,
    summary_date        DATE NOT NULL,
    total_catalysts     INTEGER,
    high_severity       INTEGER,
    critical_severity   INTEGER,
    top_catalysts       JSONB DEFAULT '[]'::jsonb,
    strategy_exposure   JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 4. News articles
CREATE TABLE IF NOT EXISTS news_articles (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    strategy_type       TEXT,
    title               TEXT NOT NULL,
    summary             TEXT,
    source              TEXT,
    source_url          TEXT,
    published_at        TIMESTAMPTZ,
    relevance_score     NUMERIC DEFAULT 0.5,
    sentiment           TEXT,
    sentiment_score     NUMERIC,
    is_attention_spike  BOOLEAN DEFAULT FALSE,
    raw_payload         JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_news_symbol ON news_articles (symbol, published_at DESC);

-- 5. News attention spikes
CREATE TABLE IF NOT EXISTS news_attention_spikes (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    spike_type          TEXT,
    article_count_24h   INTEGER,
    baseline_avg        NUMERIC,
    spike_ratio         NUMERIC,
    top_headlines       JSONB DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Catalyst sentiment analysis
CREATE TABLE IF NOT EXISTS catalyst_sentiment_analysis (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    catalyst_event_id   BIGINT,
    overall_sentiment   TEXT,
    confidence          NUMERIC,
    key_phrases         JSONB DEFAULT '[]'::jsonb,
    risk_keywords       JSONB DEFAULT '[]'::jsonb,
    opportunity_keywords JSONB DEFAULT '[]'::jsonb,
    model_used          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Social mentions
CREATE TABLE IF NOT EXISTS social_mentions (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    platform            TEXT,
    mention_text        TEXT,
    author              TEXT,
    sentiment           TEXT,
    sentiment_score     NUMERIC,
    engagement_score    NUMERIC,
    source_url          TEXT,
    published_at        TIMESTAMPTZ,
    raw_payload         JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_social_symbol ON social_mentions (symbol, published_at DESC);

-- 8. Social volume spikes
CREATE TABLE IF NOT EXISTS social_volume_spikes (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    platform            TEXT,
    mention_count_24h   INTEGER,
    baseline_avg        NUMERIC,
    spike_ratio         NUMERIC,
    dominant_sentiment  TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 9. Fused signals
CREATE TABLE IF NOT EXISTS fused_signals (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    strategy_type       TEXT,
    fused_score         NUMERIC,
    catalyst_score      NUMERIC,
    news_score          NUMERIC,
    social_score        NUMERIC,
    sentiment_score     NUMERIC,
    severity            TEXT,
    direction           TEXT,
    confidence          NUMERIC,
    strategy_alignment  NUMERIC,
    portfolio_impact_pct NUMERIC,
    contradictions      JSONB DEFAULT '[]'::jsonb,
    top_signals         JSONB DEFAULT '[]'::jsonb,
    reason_codes        TEXT[],
    human_review        BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fused_symbol ON fused_signals (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fused_severity ON fused_signals (severity, created_at DESC);

-- 10. Catalyst type weights
CREATE TABLE IF NOT EXISTS catalyst_type_weights (
    catalyst_type       TEXT PRIMARY KEY,
    base_weight         NUMERIC NOT NULL,
    description         TEXT,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO catalyst_type_weights (catalyst_type, base_weight, description) VALUES
('earnings_beat', 0.85, 'Quarterly earnings exceed expectations'),
('guidance_raise', 0.90, 'Forward guidance raised'),
('contract_win', 0.80, 'Major contract or partnership'),
('fda_approval', 0.95, 'FDA or regulatory approval'),
('merger_acquisition', 0.75, 'M&A announcement'),
('earnings_miss', 0.70, 'Quarterly earnings miss'),
('guidance_lower', 0.65, 'Forward guidance lowered'),
('insider_buy', 0.60, 'Insider purchasing shares'),
('analyst_upgrade', 0.55, 'Analyst rating upgrade'),
('short_squeeze', 0.45, 'Short squeeze potential'),
('geopolitical', 0.40, 'Geopolitical event impact'),
('dividend_increase', 0.85, 'Dividend raised'),
('dividend_cut', 0.90, 'Dividend reduced or eliminated'),
('stock_split', 0.30, 'Stock split announcement'),
('buyback', 0.55, 'Share buyback program'),
('ceo_change', 0.50, 'CEO or executive change'),
('sector_rotation', 0.45, 'Sector rotation signal')
ON CONFLICT (catalyst_type) DO NOTHING;

-- 11. Catalyst historical reactions (for learning)
CREATE TABLE IF NOT EXISTS catalyst_historical_reactions (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    strategy_type       TEXT,
    catalyst_type       TEXT,
    catalyst_date       DATE,
    price_before        NUMERIC,
    price_1d_after      NUMERIC,
    price_7d_after      NUMERIC,
    price_30d_after     NUMERIC,
    actual_reaction_pct NUMERIC,
    predicted_direction TEXT,
    prediction_correct  BOOLEAN,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

COMMIT;
