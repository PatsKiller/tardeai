-- 2026-06-09_discovery_module.sql — Hermes Discovery & Watchlist Builder. Additive.
CREATE TABLE IF NOT EXISTS discovery_queries (
    id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    mode TEXT,                      -- sector | theme | supply_chain | company | freeform
    lane TEXT,                      -- grok | chatgpt
    status TEXT DEFAULT 'pending',  -- pending | done | error
    result_count INT DEFAULT 0,
    created_by TEXT DEFAULT 'operator',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS discovery_results (
    id BIGSERIAL PRIMARY KEY,
    query_id BIGINT REFERENCES discovery_queries(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    company_name TEXT,
    relevance_score NUMERIC,        -- 0-100
    relationship_type TEXT,         -- supplier|competitor|ecosystem|direct exposure|enabling|customer|partner
    exposure_strength TEXT,         -- high|medium|low
    reason TEXT,
    verified BOOLEAN DEFAULT FALSE, -- ticker exists in our universe
    added_to_watchlist BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_discres_query ON discovery_results (query_id, relevance_score DESC);
ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS discovery_query_id BIGINT;
ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS discovery_relationship TEXT;
