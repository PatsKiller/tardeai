-- Topic Entity Linking + Curation Feedback Loop
-- 2026-05-09: Links topic content to tickers/subjects across the entire DB

-- Entity links: connects articles/transcripts to tickers and DB records
CREATE TABLE IF NOT EXISTS content_entity_links (
    id              SERIAL PRIMARY KEY,
    content_type    TEXT NOT NULL,            -- 'news_article', 'youtube_transcript'
    content_id      INTEGER NOT NULL,         -- FK to news_articles.id or youtube_transcripts.id
    entity_type     TEXT NOT NULL,            -- 'ticker', 'topic', 'sector', 'person', 'organization'
    entity_value    TEXT NOT NULL,            -- 'AAPL', 'ssdi', 'Technology', etc.
    confidence      NUMERIC(3,2) DEFAULT 0.8,-- LLM confidence 0-1
    extracted_by    TEXT DEFAULT 'llm',       -- 'llm', 'regex', 'operator'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Curation feedback: tracks what LLM learned from each ingestion run
CREATE TABLE IF NOT EXISTS topic_curation_feedback (
    id              SERIAL PRIMARY KEY,
    topic_id        TEXT NOT NULL REFERENCES topic_monitor(topic_id),
    run_date        TIMESTAMPTZ DEFAULT NOW(),
    articles_reviewed INTEGER DEFAULT 0,
    approved_count  INTEGER DEFAULT 0,
    blocked_count   INTEGER DEFAULT 0,
    tickers_extracted TEXT[] DEFAULT '{}',     -- tickers found in this run
    topics_extracted TEXT[] DEFAULT '{}',      -- related topics discovered
    suggested_queries JSONB DEFAULT '[]',      -- LLM-suggested queries for next run
    quality_summary TEXT,                      -- LLM summary of content quality
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entity_links_content ON content_entity_links(content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_entity ON content_entity_links(entity_type, entity_value);
CREATE INDEX IF NOT EXISTS idx_entity_links_ticker ON content_entity_links(entity_value) WHERE entity_type = 'ticker';
CREATE INDEX IF NOT EXISTS idx_curation_feedback_topic ON topic_curation_feedback(topic_id, run_date DESC);

-- New topics: AI data center buildout, yield/dividend, SSDI cash shield, swing, sentiment sectors
INSERT INTO topic_monitor (topic_id, display_name, search_queries, video_queries,
    priority, agent_owner, agent_tags, strategy_tags, personal_context, saved_search_urls,
    max_age_days, min_articles) VALUES

('ai_datacenter_buildout', 'AI Data Center Build-Out',
 '["AI data center infrastructure companies 2026", "data center GPU chip suppliers NVDA AMD", "AI data center power cooling companies", "hyperscaler capex spending 2026 2027"]'::jsonb,
 '["AI data center stocks infrastructure", "data center buildout investment opportunity", "companies building AI infrastructure"]'::jsonb,
 2, 'Maria', '["Maria", "Steph", "Aegis"]'::jsonb,
 '["defense_thesis", "core_growth_compounder", "speculative_growth"]'::jsonb,
 'Looking for physical infrastructure: power (EOSE, VST, CEG), networking (ANET, CSCO), chips (NVDA, AMD, AVGO, MRVL), cooling (VRT), REITs (EQIX, DLR)',
 '["https://www.google.com/search?udm=7&q=AI+data+center+infrastructure+stocks+2026"]'::jsonb,
 14, 5),

('ai_chip_materials', 'AI Chip & Materials Layer',
 '["AI chip semiconductor materials companies", "advanced packaging substrate suppliers", "HBM memory suppliers SK Hynix Micron", "AI chip supply chain companies"]'::jsonb,
 '["AI semiconductor supply chain stocks", "chip materials companies investing"]'::jsonb,
 3, 'Maria', '["Maria", "Aegis"]'::jsonb,
 '["speculative_growth", "core_growth_compounder"]'::jsonb,
 'Substrate (AMKR, ASX), memory (MU, 000660.KS), EDA (SNPS, CDNS), equipment (ASML, AMAT, LRCX, KLAC)',
 '[]'::jsonb, 14, 5),

('ai_network_layer', 'AI Networking Layer',
 '["AI networking infrastructure companies InfiniBand", "data center networking switches 2026", "optical networking AI workloads companies", "AI network fabric stocks"]'::jsonb,
 '["AI networking stocks infrastructure", "data center networking investment"]'::jsonb,
 3, 'Maria', '["Maria", "Steph"]'::jsonb,
 '["core_growth_compounder", "speculative_growth"]'::jsonb,
 'Networking (ANET, CSCO), optical (COHR, II-VI), fiber (LITE, CIEN), switches and NICs',
 '[]'::jsonb, 14, 5),

('top_yield_dividend', 'Top Yield & Dividend Stocks',
 '["highest yield dividend stocks 2026 safe", "best monthly dividend stocks retirement income", "dividend aristocrats 2026 top picks", "high yield BDC CEF 2026"]'::jsonb,
 '["best dividend stocks 2026 high yield", "monthly dividend income portfolio", "dividend aristocrats best picks"]'::jsonb,
 2, 'Steph', '["Steph", "Alex"]'::jsonb,
 '["dividend_growth_compounder", "high_yield_income_bdc", "covered_call_income", "income_add"]'::jsonb,
 'Age 58, SSDI $40K/yr, need income without triggering IRMAA, MFS filing, looking for safe 4-8% yield',
 '[]'::jsonb, 14, 5),

('ssdi_cash_shield', 'SSDI Cash & Asset Shielding',
 '["SSDI asset limits protect cash 2026", "how to shield assets on disability benefits", "SSDI bank account monitoring rules", "disability asset protection strategies New York"]'::jsonb,
 '["SSDI asset protection strategies", "how to protect money on disability", "SSDI bank account rules 2026"]'::jsonb,
 1, 'Alex', '["Alex"]'::jsonb,
 '["disability_retirement_planning"]'::jsonb,
 'Age 58, NY resident, SSDI $40K/yr, $1.19M portfolio, need to understand asset protection, ABLE accounts, special needs trusts, Medicaid lookback',
 '["https://www.google.com/search?udm=7&q=SSDI+asset+limits+protect+cash+New+York"]'::jsonb,
 30, 3),

('swing_setups', 'Top Swing Trade Setups',
 '["best swing trade stocks this week 2026", "swing trade setups breakout momentum", "top swing trading opportunities weekly", "swing trade scanner gap breakout"]'::jsonb,
 '["swing trade setups this week", "best swing trade stocks 2026", "swing trading breakout patterns"]'::jsonb,
 3, 'Steph', '["Steph", "Maria"]'::jsonb,
 '["swing_breakout", "swing_trade", "momentum_scalp", "gap_and_go"]'::jsonb,
 'Paper trading only, looking for $2-30 price range, RVOL>3, gap+momentum setups',
 '[]'::jsonb, 7, 5),

('emerging_sentiment', 'Emerging Sectors by Sentiment',
 '["emerging sector rotation 2026 momentum", "sector sentiment analysis stocks", "sector ETF momentum rotation strategy", "which sectors outperforming 2026"]'::jsonb,
 '["sector rotation strategy 2026", "emerging sectors momentum investing"]'::jsonb,
 3, 'Aegis', '["Aegis", "Maria", "Steph"]'::jsonb,
 '["sector_rotation", "speculative_growth"]'::jsonb,
 'Track sector rotation signals, identify emerging momentum before it peaks',
 '[]'::jsonb, 7, 5)

ON CONFLICT (topic_id) DO UPDATE SET
    search_queries = EXCLUDED.search_queries,
    video_queries = EXCLUDED.video_queries,
    personal_context = EXCLUDED.personal_context,
    updated_at = NOW();
