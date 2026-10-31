-- Reverse of 2026_10_31_market_quotes_extended.sql. Archives instead of dropping (AGENTS §0 rule 6); every object name
-- moves aside so the up migration can run again after a down.
ALTER TABLE IF EXISTS market_quotes_extended RENAME CONSTRAINT market_quotes_extended_uniq TO market_quotes_extended_archived_20261031_uniq;
ALTER TABLE IF EXISTS market_quotes_extended RENAME CONSTRAINT market_quotes_extended_pkey TO market_quotes_extended_archived_20261031_pkey;
ALTER INDEX IF EXISTS market_quotes_extended_symbol_inserted RENAME TO market_quotes_extended_archived_20261031_idx;
ALTER SEQUENCE IF EXISTS market_quotes_extended_id_seq RENAME TO market_quotes_extended_archived_20261031_id_seq;
ALTER TABLE IF EXISTS market_quotes_extended RENAME TO market_quotes_extended_archived_20261031;
