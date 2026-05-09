-- Topic Curation Layer: LLM-driven queries, saved search URLs, quality gating
-- 2026-05-09

-- Add saved search URLs and LLM query generation fields to topic_monitor
ALTER TABLE topic_monitor ADD COLUMN IF NOT EXISTS saved_search_urls JSONB NOT NULL DEFAULT '[]';
ALTER TABLE topic_monitor ADD COLUMN IF NOT EXISTS personal_context TEXT DEFAULT '';
ALTER TABLE topic_monitor ADD COLUMN IF NOT EXISTS llm_generated_queries JSONB DEFAULT '[]';
ALTER TABLE topic_monitor ADD COLUMN IF NOT EXISTS llm_query_refreshed_at TIMESTAMPTZ;

-- Blocked content: prevent re-downloading garbage
CREATE TABLE IF NOT EXISTS blocked_content (
    id              SERIAL PRIMARY KEY,
    content_type    TEXT NOT NULL,            -- 'youtube', 'article'
    content_id      TEXT NOT NULL,            -- video_id or source_url hash
    title           TEXT,
    reason          TEXT NOT NULL,            -- 'irrelevant', 'spam', 'low_quality', 'duplicate', 'wrong_topic'
    blocked_by      TEXT DEFAULT 'llm',       -- 'llm', 'operator', 'auto'
    topic_id        TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(content_type, content_id)
);

-- Add quality classification to youtube_transcripts
ALTER TABLE youtube_transcripts ADD COLUMN IF NOT EXISTS rag_status TEXT DEFAULT 'pending';
  -- Values: 'pending', 'approved', 'blocked', 'low_quality'
ALTER TABLE youtube_transcripts ADD COLUMN IF NOT EXISTS rag_reason TEXT DEFAULT '';

-- Add quality classification to news_articles
ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS rag_status TEXT DEFAULT 'pending';
ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS rag_reason TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_blocked_content_id ON blocked_content(content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_yt_rag_status ON youtube_transcripts(rag_status) WHERE rag_status = 'pending';
CREATE INDEX IF NOT EXISTS idx_na_rag_status ON news_articles(rag_status) WHERE rag_status = 'pending';

-- Seed the Google search URL the user provided
UPDATE topic_monitor SET saved_search_urls = '[
    "https://www.google.com/search?udm=7&q=ssdi+and+trusts+to+protect+assets+in+ny",
    "https://www.google.com/search?udm=7&q=SSDI+special+needs+trust+New+York",
    "https://www.google.com/search?udm=7&q=disability+asset+protection+trust+NY+medicaid"
]'::jsonb
WHERE topic_id = 'trust_estate';

UPDATE topic_monitor SET saved_search_urls = '[
    "https://www.google.com/search?udm=7&q=SSDI+benefits+2026+earnings+limit",
    "https://www.google.com/search?udm=7&q=social+security+disability+income+strategy"
]'::jsonb
WHERE topic_id = 'ssdi';

UPDATE topic_monitor SET saved_search_urls = '[
    "https://www.google.com/search?udm=7&q=SSDI+disability+retirement+planning+strategy",
    "https://www.google.com/search?udm=7&q=disability+retirement+income+planning+2026"
]'::jsonb
WHERE topic_id = 'disability_retirement';

-- Set personal context per topic (LLM uses this to generate better queries)
UPDATE topic_monitor SET personal_context = 'Age 58, SSDI income $40K/yr, NY resident, MFS filing, Medicare starting Dec 2026, IRMAA lookback, Roth conversion target $51K' WHERE topic_id IN ('ssdi', 'disability_retirement', 'irmaa');
UPDATE topic_monitor SET personal_context = 'Age 58, SSDI income $40K/yr, NY resident, needs asset protection trust, ABLE account eligible, Medicaid/Medicare considerations' WHERE topic_id = 'trust_estate';
UPDATE topic_monitor SET personal_context = 'Age 58, 22% bracket MFS, Roth conversion target $51K, $35K converted YTD, $16K safe room left, IRMAA 2-year lookback' WHERE topic_id = 'roth_conversion';
