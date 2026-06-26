-- In-trade adjustment guidance for open pullback positions (advisory; refreshed each monitor pass).
CREATE TABLE IF NOT EXISTS pullback_trade_adjustments (
    trade_id        INTEGER PRIMARY KEY,
    symbol          TEXT NOT NULL,
    entry           NUMERIC,
    current_stop    NUMERIC,
    suggested_stop  NUMERIC,
    target          NUMERIC,
    live_price      NUMERIC,
    vwap            NUMERIC,
    above_vwap      BOOLEAN,
    macd_falling    BOOLEAN,
    unrealized_pct  NUMERIC,
    action          TEXT,            -- hold | trail_stop | take_profit | exit_thesis_break
    rationale       TEXT,
    actionable      BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pullback_adj_action ON pullback_trade_adjustments (actionable, updated_at DESC);
