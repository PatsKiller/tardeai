-- Trade AI Agent Router migration
-- Install target: linux_port_v2/linux/migrations/004_agent_handoffs.sql or apply directly with psql.

CREATE TABLE IF NOT EXISTS agent_handoffs (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_message    TEXT NOT NULL,
    from_agent      TEXT DEFAULT 'user',
    to_agent        TEXT NOT NULL,
    intent          TEXT NOT NULL,
    confidence      NUMERIC(5,4) NOT NULL DEFAULT 0,
    reason          TEXT DEFAULT '',
    action_type     TEXT NOT NULL DEFAULT 'read_only', -- read_only | pending_write | approved_write | blocked
    status          TEXT NOT NULL DEFAULT 'routed',    -- routed | pending_approval | completed | failed | blocked
    source_required BOOLEAN NOT NULL DEFAULT FALSE,
    freshness_ok    BOOLEAN,
    payload_json    JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_handoffs_created_at ON agent_handoffs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_to_agent ON agent_handoffs(to_agent);
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_intent ON agent_handoffs(intent);
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_status ON agent_handoffs(status);

CREATE TABLE IF NOT EXISTS agent_decision_journal (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_name      TEXT NOT NULL,
    decision_type   TEXT NOT NULL, -- ADD | TRIM | HOLD | WATCH | HONOR_STOP | DELAY | RESEARCH_ONLY
    ticker          TEXT,
    account         TEXT,
    dollar_amount   NUMERIC(14,2),
    confidence      NUMERIC(5,4),
    recommendation  TEXT NOT NULL,
    rationale       TEXT DEFAULT '',
    source_links    JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_json    JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_decision_journal_created_at ON agent_decision_journal(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_decision_journal_ticker ON agent_decision_journal(ticker);
CREATE INDEX IF NOT EXISTS idx_agent_decision_journal_agent ON agent_decision_journal(agent_name);
