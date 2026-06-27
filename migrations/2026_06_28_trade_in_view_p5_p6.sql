-- TradeInView P5-P6: attachments, session recaps, options leg groups

CREATE TABLE IF NOT EXISTS journal_attachments (
    id BIGSERIAL PRIMARY KEY,
    trade_key TEXT,
    session_date DATE,
    kind TEXT NOT NULL DEFAULT 'screenshot',
    filename TEXT NOT NULL,
    mime_type TEXT,
    storage_path TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_journal_attach_trade ON journal_attachments (trade_key);
CREATE INDEX IF NOT EXISTS idx_journal_attach_session ON journal_attachments (session_date);

CREATE TABLE IF NOT EXISTS journal_session_recaps (
    id BIGSERIAL PRIMARY KEY,
    session_date DATE NOT NULL UNIQUE,
    account TEXT,
    pre_market_plan TEXT,
    eod_reflection TEXT,
    planned_trades JSONB DEFAULT '[]'::jsonb,
    actual_pnl NUMERIC,
    trades_count INTEGER,
    tilt_detected BOOLEAN DEFAULT FALSE,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS journal_options_groups (
    id BIGSERIAL PRIMARY KEY,
    group_key TEXT NOT NULL UNIQUE,
    underlying TEXT NOT NULL,
    account TEXT,
    strategy_label TEXT,
    close_date DATE,
    net_pnl NUMERIC,
    legs JSONB NOT NULL DEFAULT '[]'::jsonb,
    book_greeks JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_journal_opt_grp_under ON journal_options_groups (underlying, close_date DESC);