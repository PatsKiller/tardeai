-- Session 26: Proposal enrichment packet state columns + audit tables

ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS packet_state TEXT DEFAULT 'NEW',
ADD COLUMN IF NOT EXISTS packet_completion_pct NUMERIC DEFAULT 0,
ADD COLUMN IF NOT EXISTS packet_last_enriched_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS packet_next_refresh_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS packet_blockers JSONB,
ADD COLUMN IF NOT EXISTS packet_warnings JSONB,
ADD COLUMN IF NOT EXISTS missing_data_by_section JSONB,
ADD COLUMN IF NOT EXISTS action_state TEXT,
ADD COLUMN IF NOT EXISTS action_label TEXT,
ADD COLUMN IF NOT EXISTS top_blocker TEXT,
ADD COLUMN IF NOT EXISTS next_actions JSONB,
ADD COLUMN IF NOT EXISTS llm_review_status TEXT DEFAULT 'NOT_REQUESTED',
ADD COLUMN IF NOT EXISTS llm_review_queued_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS enrichment_attempt_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_enrichment_error TEXT;

-- Enrichment audit events
CREATE TABLE IF NOT EXISTS proposal_enrichment_events (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    event_type TEXT NOT NULL,
    stage TEXT,
    status TEXT,
    message TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pee_proposal_created
ON proposal_enrichment_events(proposal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pee_stage_created
ON proposal_enrichment_events(stage, created_at DESC);

-- LLM review queue
CREATE TABLE IF NOT EXISTS proposal_llm_review_queue (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    queue_status TEXT DEFAULT 'PENDING',
    priority INTEGER DEFAULT 5,
    model TEXT DEFAULT 'qwen3:14b',
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    queued_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    UNIQUE(proposal_id)
);
