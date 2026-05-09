-- Session 28: Paper execution submit/close workflow
-- Date: 2026-05-08

-- Proposal submit tracking
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS paper_submit_state TEXT DEFAULT 'NOT_SUBMITTED',
ADD COLUMN IF NOT EXISTS paper_submit_blockers JSONB,
ADD COLUMN IF NOT EXISTS paper_submit_warnings JSONB,
ADD COLUMN IF NOT EXISTS paper_submit_checked_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS paper_submitted_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS paper_client_order_id TEXT,
ADD COLUMN IF NOT EXISTS paper_broker_order_id TEXT,
ADD COLUMN IF NOT EXISTS paper_submit_payload JSONB,
ADD COLUMN IF NOT EXISTS paper_submit_result JSONB;

-- Paper trades broker integration columns
ALTER TABLE paper_trades
ADD COLUMN IF NOT EXISTS broker TEXT DEFAULT 'alpaca_paper',
ADD COLUMN IF NOT EXISTS client_order_id TEXT,
ADD COLUMN IF NOT EXISTS bracket_order BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS take_profit_price NUMERIC,
ADD COLUMN IF NOT EXISTS stop_loss_price NUMERIC,
ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS close_requested_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS close_reason TEXT,
ADD COLUMN IF NOT EXISTS close_order_id TEXT,
ADD COLUMN IF NOT EXISTS close_result JSONB;

-- Paper execution events (immutable audit log)
CREATE TABLE IF NOT EXISTS paper_execution_events (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER,
    paper_trade_id INTEGER,
    symbol TEXT,
    event_type TEXT NOT NULL,
    event_status TEXT,
    broker TEXT DEFAULT 'alpaca_paper',
    client_order_id TEXT,
    broker_order_id TEXT,
    message TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pee2_proposal_created
ON paper_execution_events(proposal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pee2_trade_created
ON paper_execution_events(paper_trade_id, created_at DESC);

-- Unique constraint on client_order_id for idempotency
CREATE UNIQUE INDEX IF NOT EXISTS idx_pt_client_order_id
ON paper_trades(client_order_id) WHERE client_order_id IS NOT NULL;
