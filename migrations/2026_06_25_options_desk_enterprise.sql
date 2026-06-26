-- Enterprise options desk: operator approval queue + vol chain snapshots.

CREATE TABLE IF NOT EXISTS options_approval_queue (
    id              BIGSERIAL PRIMARY KEY,
    proposal_id     TEXT NOT NULL UNIQUE,
    symbol          TEXT,
    strategy        TEXT,
    desk_tier       TEXT DEFAULT 'C',
    edge_score      NUMERIC,
    status          TEXT NOT NULL DEFAULT 'pending',
    live_eligible   BOOLEAN DEFAULT FALSE,
    blocks_json     JSONB DEFAULT '[]'::jsonb,
    proposal_json   JSONB,
    reviewer        TEXT,
    review_note     TEXT,
    reviewed_at     TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_options_approval_status ON options_approval_queue (status, edge_score DESC);
CREATE INDEX IF NOT EXISTS idx_options_approval_symbol ON options_approval_queue (symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS options_chain_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    chain_json          JSONB,
    vol_analytics_json  JSONB,
    captured_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_options_chain_snap_sym_time ON options_chain_snapshots (symbol, captured_at DESC);