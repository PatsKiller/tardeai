-- VWAP entry-timing confirmation on pullback/MACD candidates.
ALTER TABLE pullback_macd_candidates ADD COLUMN IF NOT EXISTS vwap NUMERIC;
ALTER TABLE pullback_macd_candidates ADD COLUMN IF NOT EXISTS above_vwap BOOLEAN;
ALTER TABLE pullback_macd_candidates ADD COLUMN IF NOT EXISTS vwap_dist_pct NUMERIC;
