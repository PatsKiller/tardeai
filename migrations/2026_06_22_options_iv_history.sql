-- Options IV history for true IV rank (52-week window per symbol).
CREATE TABLE IF NOT EXISTS options_iv_history (
    id           BIGSERIAL PRIMARY KEY,
    symbol       TEXT NOT NULL,
    iv_pct       NUMERIC NOT NULL,
    atm_strike   NUMERIC,
    underlying   NUMERIC,
    source       TEXT DEFAULT 'schwab_chain',
    captured_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_options_iv_sym_time ON options_iv_history (symbol, captured_at DESC);