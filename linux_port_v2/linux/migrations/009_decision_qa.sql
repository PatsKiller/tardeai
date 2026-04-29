-- 009_decision_qa.sql — Decision QA: contradiction detection, gating, actionability
-- Run: PGPASSWORD=... psql -h localhost -U trade_ai -d trade_ai -f linux_port_v2/linux/migrations/009_decision_qa.sql

BEGIN;

-- Extend watchlist_final_synthesis with QA fields
ALTER TABLE watchlist_final_synthesis
    ADD COLUMN IF NOT EXISTS decision_quality_status TEXT DEFAULT 'pending'
        CHECK (decision_quality_status IN (
            'actionable', 'partial_review', 'conflicting_agents',
            'missing_required_agent', 'data_quality_warning',
            'data_quality_blocked', 'tiny_position_low_priority',
            'stale_analysis', 'needs_human_review', 'pending'
        )),
    ADD COLUMN IF NOT EXISTS conflicts_detected JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS gating_reasons JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS actionable BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS human_review_required BOOLEAN DEFAULT FALSE;

-- Also add to maturity for symbols without synthesis yet
ALTER TABLE watchlist_analysis_maturity
    ADD COLUMN IF NOT EXISTS decision_quality_status TEXT DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS actionable BOOLEAN DEFAULT FALSE;

COMMIT;
