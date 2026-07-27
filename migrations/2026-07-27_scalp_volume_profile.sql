-- M3-S1: per-symbol intraday volume profile for time-of-day RVOL (RVOL_tod).
-- Momentum Scalp Signal Engine. Shadow/read-model only — structurally isolated from
-- paper_trade_proposals and any order path (no FK, no reference).
-- See docs/strategies/MOMENTUM_SCALP_SIGNAL_ENGINE_v1.md §3.1.

CREATE TABLE IF NOT EXISTS symbol_volume_profile (
    id                 BIGSERIAL PRIMARY KEY,
    symbol             TEXT        NOT NULL,
    session_window     TEXT        NOT NULL DEFAULT 'regular',  -- 'regular' | 'premarket'
    minute_of_session  SMALLINT    NOT NULL,                    -- 0..389 for regular (09:30..15:59 ET)
    median_cum_volume  NUMERIC     NOT NULL,                    -- trailing-N-session median CUMULATIVE volume at this minute
    median_incr_volume NUMERIC,                                 -- trailing-N-session median per-minute (incremental) volume
    n_sessions         SMALLINT    NOT NULL,                    -- complete sessions used
    feed               TEXT        NOT NULL,                    -- 'sip' | 'iex' (must match the live RVOL_tod feed)
    lookback_sessions  SMALLINT    NOT NULL,
    built_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, session_window, feed, minute_of_session)
);

CREATE INDEX IF NOT EXISTS idx_svp_symbol ON symbol_volume_profile (symbol, session_window, feed);
CREATE INDEX IF NOT EXISTS idx_svp_built  ON symbol_volume_profile (built_at);
