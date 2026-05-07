-- Session 15: Agent Curation, Open Trade Monitor, Local LLM Post-Trade Analysis
-- 2026-05-06

-- 2.1 open_trade_alerts
CREATE TABLE IF NOT EXISTS open_trade_alerts (
    id SERIAL PRIMARY KEY,
    paper_trade_id INTEGER,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    alert_type TEXT NOT NULL,
    severity TEXT DEFAULT 'INFO',
    title TEXT,
    message TEXT,
    data JSONB,
    sent_telegram BOOLEAN DEFAULT false,
    acknowledged BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_open_trade_alerts_trade
ON open_trade_alerts(paper_trade_id);

CREATE INDEX IF NOT EXISTS idx_open_trade_alerts_created
ON open_trade_alerts(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_open_trade_alerts_unacked
ON open_trade_alerts(acknowledged, severity);

-- 2.2 paper_trade_analysis
CREATE TABLE IF NOT EXISTS paper_trade_analysis (
    id SERIAL PRIMARY KEY,
    paper_trade_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    model_used TEXT,
    analysis_type TEXT DEFAULT 'post_trade',
    prompt_hash TEXT,
    summary TEXT,
    worked_reasons JSONB,
    failed_reasons JSONB,
    lessons JSONB,
    suggested_rule_changes JSONB,
    confidence NUMERIC,
    created_by TEXT DEFAULT 'local_llm',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(paper_trade_id, analysis_type)
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_analysis_trade
ON paper_trade_analysis(paper_trade_id);

CREATE INDEX IF NOT EXISTS idx_paper_trade_analysis_created
ON paper_trade_analysis(created_at DESC);

-- 2.3 agent_curation_events
CREATE TABLE IF NOT EXISTS agent_curation_events (
    id SERIAL PRIMARY KEY,
    paper_trade_id INTEGER,
    proposal_id INTEGER,
    symbol TEXT,
    strategy_id TEXT,
    agent_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_summary TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_curation_events_agent
ON agent_curation_events(agent_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_curation_events_trade
ON agent_curation_events(paper_trade_id);

-- 2.4 local_llm_runs
CREATE TABLE IF NOT EXISTS local_llm_runs (
    id SERIAL PRIMARY KEY,
    model_name TEXT,
    status TEXT NOT NULL,
    run_type TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    duration_sec NUMERIC,
    items_processed INTEGER DEFAULT 0,
    items_failed INTEGER DEFAULT 0,
    last_error TEXT,
    payload JSONB
);

CREATE INDEX IF NOT EXISTS idx_local_llm_runs_created
ON local_llm_runs(started_at DESC);

-- 2.5 Enrich paper_trades
ALTER TABLE paper_trades
ADD COLUMN IF NOT EXISTS monitored_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS last_alert_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS stale_flag BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS thesis_status TEXT,
ADD COLUMN IF NOT EXISTS post_trade_analyzed BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS iris_curated BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS aegis_summarized BOOLEAN DEFAULT false;

-- 2.6 Proposal quality filtering
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS quality_pass BOOLEAN,
ADD COLUMN IF NOT EXISTS quality_reason_codes JSONB,
ADD COLUMN IF NOT EXISTS hidden_by_quality_filter BOOLEAN DEFAULT false;
