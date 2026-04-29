CREATE TABLE IF NOT EXISTS agent_context_refreshes (id SERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), refresh_type TEXT NOT NULL, status TEXT NOT NULL, files_checked JSONB DEFAULT '[]'::jsonb, files_written JSONB DEFAULT '[]'::jsonb, freshness_issues JSONB DEFAULT '[]'::jsonb, notes TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_agent_context_refreshes_created ON agent_context_refreshes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_context_refreshes_type ON agent_context_refreshes(refresh_type);
CREATE TABLE IF NOT EXISTS agent_chain_runs (id SERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), user_message TEXT NOT NULL, route JSONB NOT NULL, chain JSONB NOT NULL, status TEXT NOT NULL, result JSONB DEFAULT '{}'::jsonb, dry_run BOOLEAN NOT NULL DEFAULT TRUE);
CREATE INDEX IF NOT EXISTS idx_agent_chain_runs_created ON agent_chain_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_chain_runs_status ON agent_chain_runs(status);
