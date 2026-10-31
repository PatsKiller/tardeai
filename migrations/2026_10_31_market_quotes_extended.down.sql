-- Reverse of 2026_10_31_market_quotes_extended.sql. Archives instead of dropping (AGENTS §0 rule 6). One transaction;
-- repeatable: each rename runs only when its source exists and its target name is free, so a second down (or a down
-- after a later up/down cycle) never fails half-way. Archive names carry the run date to stay unique.
BEGIN;
DO $$
DECLARE
    sfx text := 'archived_' || to_char(now(), 'YYYYMMDD_HH24MISS');
BEGIN
    IF to_regclass('market_quotes_extended') IS NULL THEN
        RAISE NOTICE 'market_quotes_extended absent: nothing to archive';
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_quotes_extended_uniq') THEN
        EXECUTE format('ALTER TABLE market_quotes_extended RENAME CONSTRAINT market_quotes_extended_uniq TO %I',
                       'market_quotes_extended_' || sfx || '_uniq');
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_quotes_extended_pkey') THEN
        EXECUTE format('ALTER TABLE market_quotes_extended RENAME CONSTRAINT market_quotes_extended_pkey TO %I',
                       'market_quotes_extended_' || sfx || '_pkey');
    END IF;
    IF to_regclass('idx_market_quotes_extended_symbol_inserted') IS NOT NULL THEN
        EXECUTE format('ALTER INDEX idx_market_quotes_extended_symbol_inserted RENAME TO %I',
                       'idx_market_quotes_extended_' || sfx);
    END IF;
    IF to_regclass('market_quotes_extended_id_seq') IS NOT NULL THEN
        EXECUTE format('ALTER SEQUENCE market_quotes_extended_id_seq RENAME TO %I',
                       'market_quotes_extended_' || sfx || '_id_seq');
    END IF;
    EXECUTE format('ALTER TABLE market_quotes_extended RENAME TO %I', 'market_quotes_extended_' || sfx);
END $$;
COMMIT;
