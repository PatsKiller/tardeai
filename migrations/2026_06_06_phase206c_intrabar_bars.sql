-- Phase 206c — Intrabar price-path ingestion for honest premature-exit pricing.
-- Evidence-only analytics. No execution/strategy/order/GO-WAIT impact. Idempotent.
--
-- Stores the ACTUAL ordered OHLC path of each closed measurable trade (entry->exit) so the
-- profit-protection rule backtest can REPLAY a candidate stop/trail/lock against the real path and
-- measure premature-exit cost — instead of the single-peak MFE approximation that cannot order a
-- stop trigger against later profit. Bars are read-only market data (yfinance); never fabricated.

CREATE TABLE IF NOT EXISTS trade_intrabar_bars (
  id BIGSERIAL PRIMARY KEY,
  trade_instance_id BIGINT REFERENCES trade_instances(id),
  symbol TEXT,
  bar_seq INTEGER,            -- 0-based order within the hold window
  bar_time TIMESTAMPTZ,
  open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC, volume NUMERIC,
  timeframe TEXT,
  source TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (trade_instance_id, bar_seq)
);
CREATE INDEX IF NOT EXISTS idx_tib_ti ON trade_intrabar_bars(trade_instance_id);

-- Per-trade ingestion coverage log (honest: status records why a path is/ isn't available).
CREATE TABLE IF NOT EXISTS trade_intrabar_ingest_log (
  trade_instance_id BIGINT PRIMARY KEY REFERENCES trade_instances(id),
  symbol TEXT,
  window_start TIMESTAMPTZ,
  window_end TIMESTAMPTZ,
  timeframe TEXT,
  bars_ingested INTEGER,
  status TEXT,                -- ok | no_bars | fetch_error | out_of_range | not_long
  note TEXT,
  ingested_at TIMESTAMPTZ DEFAULT now()
);
