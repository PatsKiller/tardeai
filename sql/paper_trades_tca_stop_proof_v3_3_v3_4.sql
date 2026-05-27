ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS order_submitted_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS order_filled_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_order_id TEXT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_verified_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_paper_trades_order_submitted_at ON paper_trades(order_submitted_at);
CREATE INDEX IF NOT EXISTS idx_paper_trades_order_filled_at ON paper_trades(order_filled_at);
CREATE INDEX IF NOT EXISTS idx_paper_trades_stop_order_id ON paper_trades(stop_order_id);
