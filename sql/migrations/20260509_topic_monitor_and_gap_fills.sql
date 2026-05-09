-- Topic Monitor & Iris Gap Remediation Tables
-- 2026-05-09: Cloud Product Rebuild

-- Topic monitor: defines what non-symbol topics to track
CREATE TABLE IF NOT EXISTS topic_monitor (
    id              SERIAL PRIMARY KEY,
    topic_id        TEXT UNIQUE NOT NULL,          -- e.g. 'disability_retirement'
    display_name    TEXT NOT NULL,                  -- e.g. 'Disability Retirement'
    search_queries  JSONB NOT NULL DEFAULT '[]',   -- tight queries: ["SSDI benefits 2026", "disability retirement planning"]
    video_queries   JSONB NOT NULL DEFAULT '[]',   -- YouTube-specific: ["SSDI retirement strategy", "disability income planning"]
    priority        INTEGER NOT NULL DEFAULT 5,     -- 1=highest, 10=lowest
    agent_owner     TEXT NOT NULL DEFAULT 'Alex',   -- primary agent
    agent_tags      JSONB NOT NULL DEFAULT '[]',   -- additional agents: ["Alex", "Aegis"]
    strategy_tags   JSONB NOT NULL DEFAULT '[]',   -- ["disability_retirement_planning", "retirement_planning"]
    max_age_days    INTEGER NOT NULL DEFAULT 30,    -- alert threshold
    min_articles    INTEGER NOT NULL DEFAULT 3,     -- minimum articles expected in max_age_days
    enabled         BOOLEAN NOT NULL DEFAULT true,
    last_searched   TIMESTAMPTZ,
    last_found_count INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Gap fill log: tracks what Iris auto-remediated
CREATE TABLE IF NOT EXISTS iris_library_gap_fills (
    id              SERIAL PRIMARY KEY,
    topic_id        TEXT NOT NULL REFERENCES topic_monitor(topic_id),
    source          TEXT NOT NULL,                  -- 'youtube_api', 'google_news_rss', 'brave', 'duckduckgo'
    query_used      TEXT NOT NULL,
    results_found   INTEGER NOT NULL DEFAULT 0,
    articles_saved  INTEGER NOT NULL DEFAULT 0,
    transcripts_saved INTEGER NOT NULL DEFAULT 0,
    llm_normalized  BOOLEAN NOT NULL DEFAULT false,
    search_time_ms  INTEGER,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_topic_monitor_enabled ON topic_monitor(enabled) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_gap_fills_topic ON iris_library_gap_fills(topic_id, created_at DESC);

-- Seed topics
INSERT INTO topic_monitor (topic_id, display_name, search_queries, video_queries, priority, agent_owner, agent_tags, strategy_tags, max_age_days, min_articles) VALUES
('disability_retirement', 'Disability Retirement',
 '["SSDI disability retirement planning 2026", "social security disability benefits strategy"]'::jsonb,
 '["SSDI retirement income strategy", "disability retirement planning tips"]'::jsonb,
 1, 'Alex', '["Alex", "Aegis"]'::jsonb, '["disability_retirement_planning", "retirement_planning"]'::jsonb, 30, 3),

('ssdi', 'SSDI Benefits',
 '["SSDI benefits update 2026", "social security disability income limits", "SSDI earnings limit 2026"]'::jsonb,
 '["SSDI benefits explained 2026", "social security disability update"]'::jsonb,
 1, 'Alex', '["Alex"]'::jsonb, '["disability_retirement_planning"]'::jsonb, 30, 3),

('trust_estate', 'Trust & Estate Planning',
 '["special needs trust planning 2026", "ABLE account disability", "estate planning disabled beneficiary"]'::jsonb,
 '["special needs trust explained", "ABLE account benefits disabled"]'::jsonb,
 2, 'Alex', '["Alex"]'::jsonb, '["disability_retirement_planning", "retirement_planning"]'::jsonb, 30, 3),

('roth_conversion', 'Roth Conversion Strategy',
 '["Roth conversion strategy 2026", "Roth IRA conversion tax bracket", "backdoor Roth IRA rules"]'::jsonb,
 '["Roth conversion strategy low income", "Roth IRA conversion planning"]'::jsonb,
 2, 'Alex', '["Alex", "Steph"]'::jsonb, '["retirement_planning"]'::jsonb, 30, 5),

('irmaa', 'IRMAA Medicare Surcharge',
 '["IRMAA threshold 2026 2027", "Medicare Part B premium surcharge", "IRMAA income limits married"]'::jsonb,
 '["IRMAA explained Medicare premium", "Medicare surcharge planning"]'::jsonb,
 2, 'Alex', '["Alex"]'::jsonb, '["retirement_planning", "disability_retirement_planning"]'::jsonb, 30, 3),

('covered_call_income', 'Covered Call Income',
 '["covered call income strategy 2026", "covered call ETF dividend", "selling covered calls retirement"]'::jsonb,
 '["covered call income strategy", "selling covered calls for income"]'::jsonb,
 3, 'Steph', '["Steph", "Alex"]'::jsonb, '["covered_call_income", "tactical_income"]'::jsonb, 30, 5),

('dividend_income', 'Dividend Income Strategy',
 '["high dividend stocks 2026", "dividend growth investing retirement", "monthly dividend income portfolio"]'::jsonb,
 '["dividend income portfolio 2026", "best dividend stocks retirement"]'::jsonb,
 3, 'Steph', '["Steph", "Alex"]'::jsonb, '["dividend_growth_compounder", "high_yield_income_bdc"]'::jsonb, 30, 5),

('defense_sector', 'Defense Sector Thesis',
 '["defense stocks AI military 2026", "defense budget spending increase", "defense sector ETF outlook"]'::jsonb,
 '["defense stocks AI warfare", "military spending 2026 outlook"]'::jsonb,
 3, 'Maria', '["Maria", "Aegis"]'::jsonb, '["defense_thesis"]'::jsonb, 30, 5),

('bond_rates', 'Bond & Interest Rate',
 '["Treasury bond yields 2026", "interest rate forecast Fed", "bond income strategy rising rates"]'::jsonb,
 '["bond investing strategy 2026", "Treasury yield forecast"]'::jsonb,
 4, 'Steph', '["Steph", "Alex"]'::jsonb, '["bond_income"]'::jsonb, 30, 5),

('tax_loss_harvest', 'Tax Loss Harvesting',
 '["tax loss harvesting rules 2026", "wash sale rule strategy", "tax loss harvest year end"]'::jsonb,
 '["tax loss harvesting explained", "wash sale rule tips"]'::jsonb,
 5, 'Alex', '["Alex"]'::jsonb, '["tax_loss_harvest"]'::jsonb, 30, 3)

ON CONFLICT (topic_id) DO UPDATE SET
    search_queries = EXCLUDED.search_queries,
    video_queries = EXCLUDED.video_queries,
    updated_at = NOW();
