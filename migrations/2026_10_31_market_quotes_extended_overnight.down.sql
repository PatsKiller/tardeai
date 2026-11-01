-- Reverse of 2026_10_31_market_quotes_extended_overnight.sql. Never deletes (AGENTS §0 rule 6): when any overnight,
-- futures_open or reference-less row exists it REFUSES and names the count, so the operator archives those rows first
-- (rename/copy, with a tripwire). Otherwise it restores #2384's contract: session in (premarket, afterhours) and
-- reference_close / reference_date / change_pct NOT NULL. One transaction; repeatable.
BEGIN;
DO $$
DECLARE
    n bigint;
BEGIN
    IF to_regclass('market_quotes_extended') IS NULL THEN
        RAISE NOTICE 'market_quotes_extended absent: nothing to reverse';
        RETURN;
    END IF;
    SELECT count(*) INTO n FROM market_quotes_extended
    WHERE session NOT IN ('premarket', 'afterhours')
       OR reference_close IS NULL OR reference_date IS NULL OR change_pct IS NULL;
    IF n > 0 THEN
        RAISE EXCEPTION 'refused: % overnight/futures_open or reference-less rows in market_quotes_extended; archive them first (never deleted by a down migration)', n;
    END IF;
    ALTER TABLE market_quotes_extended DROP CONSTRAINT IF EXISTS market_quotes_extended_reference_ck;
    ALTER TABLE market_quotes_extended DROP CONSTRAINT IF EXISTS market_quotes_extended_session_check;
    ALTER TABLE market_quotes_extended
        ADD CONSTRAINT market_quotes_extended_session_check CHECK (session IN ('premarket', 'afterhours'));
    ALTER TABLE market_quotes_extended
        ALTER COLUMN reference_close SET NOT NULL,
        ALTER COLUMN reference_date SET NOT NULL,
        ALTER COLUMN change_pct SET NOT NULL;
END $$;
COMMIT;
