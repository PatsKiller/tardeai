-- Extended-session (pre-market / after-hours) prints for the Market Risk Engine (DSN-20261031-market-risk-engine P1-T4).
-- Its own store, never market_quotes: market_quotes is the latest-quote ledger and ~20 readers take its newest row with
-- no source filter (review of #2384). Single writer: scripts/lib/writers/market_quotes_extended_writer.py.
-- Idempotent: safe to re-run.
CREATE TABLE IF NOT EXISTS market_quotes_extended (
    id               BIGSERIAL PRIMARY KEY,
    symbol           TEXT        NOT NULL,
    session          TEXT        NOT NULL CHECK (session IN ('premarket', 'afterhours')),
    session_date     DATE        NOT NULL,           -- the NYSE trading day the print belongs to
    bar_start        TIMESTAMPTZ NOT NULL,
    bar_end          TIMESTAMPTZ NOT NULL,           -- the print was not knowable before this instant
    price            NUMERIC     NOT NULL CHECK (price > 0),
    volume           BIGINT,
    reference_close  NUMERIC     NOT NULL CHECK (reference_close > 0),
    reference_date   DATE        NOT NULL,           -- the session whose close is the reference
    reference_basis  TEXT        NOT NULL,           -- how reference_close was obtained (labelled, review M1)
    change_pct       NUMERIC     NOT NULL,
    feed             TEXT        NOT NULL,           -- alpaca feed (sip / iex)
    inserted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),  -- knowability for replays (review M2)
    CONSTRAINT market_quotes_extended_uniq UNIQUE (symbol, bar_start, feed)
);
CREATE INDEX IF NOT EXISTS market_quotes_extended_symbol_inserted
    ON market_quotes_extended (symbol, inserted_at DESC);
