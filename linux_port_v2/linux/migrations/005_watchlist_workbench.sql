-- Migration 005: Watchlist Agent Workbench
-- Canonical DB-backed watchlist with agent processing pipeline
-- Run: PGPASSWORD=... psql -h localhost -U trade_ai -d trade_ai -f 005_watchlist_workbench.sql

-- 1. Recreate watchlist_items with proper schema for workbench
-- (old table had different columns — rename and recreate)
ALTER TABLE IF EXISTS watchlist_items RENAME TO watchlist_items_legacy;

CREATE TABLE IF NOT EXISTS watchlist_items (
    id serial PRIMARY KEY,
    symbol text NOT NULL,
    asset_type text,
    source text NOT NULL,  -- portfolio, ai_discovered, ai_watchlist, personal_watchlist
    bucket text,
    status text NOT NULL DEFAULT 'active',  -- active, queued, researching, researched, review, removed, promoted
    score numeric,
    trend text,
    backtest_score numeric,
    backtest_data jsonb DEFAULT '{}',
    trade_plan jsonb DEFAULT '{}',
    source_payload jsonb DEFAULT '{}',
    first_seen_at timestamptz DEFAULT now(),
    last_seen_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    UNIQUE(symbol, source, COALESCE(bucket, ''))
);

CREATE INDEX IF NOT EXISTS idx_wi_symbol ON watchlist_items(symbol);
CREATE INDEX IF NOT EXISTS idx_wi_source ON watchlist_items(source);
CREATE INDEX IF NOT EXISTS idx_wi_bucket ON watchlist_items(bucket);
CREATE INDEX IF NOT EXISTS idx_wi_status ON watchlist_items(status);
CREATE INDEX IF NOT EXISTS idx_wi_updated ON watchlist_items(updated_at DESC);

-- 2. Agent jobs table
CREATE TABLE IF NOT EXISTS watchlist_agent_jobs (
    id text PRIMARY KEY,
    symbol text NOT NULL,
    requested_agent text NOT NULL,
    request_type text NOT NULL,
    note text,
    status text NOT NULL DEFAULT 'queued',  -- queued, processing, completed, failed, needs_iteration
    priority integer DEFAULT 5,
    submitted_from text DEFAULT 'command_center',
    created_at timestamptz DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    payload jsonb DEFAULT '{}',
    result_id text
);

CREATE INDEX IF NOT EXISTS idx_waj_status ON watchlist_agent_jobs(status);
CREATE INDEX IF NOT EXISTS idx_waj_agent ON watchlist_agent_jobs(requested_agent);
CREATE INDEX IF NOT EXISTS idx_waj_symbol ON watchlist_agent_jobs(symbol);
CREATE INDEX IF NOT EXISTS idx_waj_created ON watchlist_agent_jobs(created_at DESC);

-- 3. Agent results table
CREATE TABLE IF NOT EXISTS watchlist_agent_results (
    id text PRIMARY KEY,
    job_id text REFERENCES watchlist_agent_jobs(id),
    symbol text NOT NULL,
    agent text,
    request_type text,
    status text,
    confidence numeric,
    summary text,
    recommendation text,
    next_action text,
    full_result jsonb DEFAULT '{}',
    route jsonb DEFAULT '{}',
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_war_symbol ON watchlist_agent_results(symbol);
CREATE INDEX IF NOT EXISTS idx_war_agent ON watchlist_agent_results(agent);
CREATE INDEX IF NOT EXISTS idx_war_created ON watchlist_agent_results(created_at DESC);

-- 4. Research cards (upsert-friendly)
DROP TABLE IF EXISTS watchlist_research_cards;
CREATE TABLE watchlist_research_cards (
    symbol text PRIMARY KEY,
    card jsonb NOT NULL DEFAULT '{}',
    research_status text,
    latest_summary text,
    latest_recommendation text,
    needs_iteration boolean DEFAULT false,
    confidence numeric,
    updated_at timestamptz DEFAULT now()
);

-- 5. Events table (append-only audit log)
CREATE TABLE IF NOT EXISTS watchlist_events (
    id serial PRIMARY KEY,
    event_type text NOT NULL,
    symbol text,
    source text,
    agent text,
    status text,
    message text,
    payload jsonb DEFAULT '{}',
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_we_type ON watchlist_events(event_type);
CREATE INDEX IF NOT EXISTS idx_we_created ON watchlist_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_we_symbol ON watchlist_events(symbol);

-- Done
SELECT 'Migration 005 complete' as status;
