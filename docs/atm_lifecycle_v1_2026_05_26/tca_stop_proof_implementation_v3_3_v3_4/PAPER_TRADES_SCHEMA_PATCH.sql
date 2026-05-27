-- v3.3/v3.4 Paper Trades Schema Patch
-- Adds nullable timing and stop proof columns. Non-destructive.

ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS order_submitted_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS order_filled_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_order_id TEXT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_verified_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_pt_order_submitted ON paper_trades(order_submitted_at);
CREATE INDEX IF NOT EXISTS idx_pt_order_filled ON paper_trades(order_filled_at);
CREATE INDEX IF NOT EXISTS idx_pt_stop_order ON paper_trades(stop_order_id);

-- SQLite note: SQLite supports ALTER TABLE ADD COLUMN but not IF NOT EXISTS.
-- For SQLite environments, check column existence first or catch the error.
