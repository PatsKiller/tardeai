BEGIN;

ALTER TABLE paper_trades
ADD COLUMN IF NOT EXISTS broker_order_id TEXT,
ADD COLUMN IF NOT EXISTS broker_status TEXT,
ADD COLUMN IF NOT EXISTS order_type TEXT,
ADD COLUMN IF NOT EXISTS source_signal_id INTEGER,
ADD COLUMN IF NOT EXISTS source_strategy_card_id INTEGER,
ADD COLUMN IF NOT EXISTS risk_gate_result TEXT,
ADD COLUMN IF NOT EXISTS risk_gate_reason_codes JSONB,
ADD COLUMN IF NOT EXISTS opened_via TEXT,
ADD COLUMN IF NOT EXISTS closed_via TEXT,
ADD COLUMN IF NOT EXISTS current_price NUMERIC,
ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC,
ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS notes TEXT;

CREATE INDEX IF NOT EXISTS idx_paper_trades_account_status ON paper_trades(account, status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol_status ON paper_trades(symbol, status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_closed ON paper_trades(closed_at DESC);

CREATE TABLE IF NOT EXISTS paper_trade_commands (
    id SERIAL PRIMARY KEY,
    command_text TEXT,
    command_type TEXT,
    symbol TEXT,
    result TEXT,
    response_text TEXT,
    chat_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_trade_commands_created ON paper_trade_commands(created_at DESC);

COMMIT;
