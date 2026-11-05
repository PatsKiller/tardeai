-- Overnight and Sunday futures-open sessions in market_quotes_extended (Market Risk Engine, DSN-20261031; operator
-- 2026-10-31: the engine must see 20:00-04:00 ET and index futures from the Sunday 18:00 open). Applies AFTER
-- 2026_10_31_market_quotes_extended.sql (#2384) and refuses to run without it. Single writer unchanged:
-- scripts/lib/writers/market_quotes_extended_writer.py. Session definitions: scripts/lib/overnight_session.py.
--
-- ADDITIVE ONLY. No row is updated, deleted or rewritten:
--   1. the session CHECK widens from (premarket, afterhours) to (premarket, afterhours, overnight, futures_open);
--   2. reference_close / reference_date / change_pct lose NOT NULL (catalog-only change), and a new CHECK keeps them
--      REQUIRED for premarket/afterhours. Only overnight/futures_open rows may store a level without a reference,
--      and then all three must be NULL together: a payload without a settlement or previous close stores the level,
--      never an invented reference. reference_basis stays NOT NULL (it names the basis, or that there is none).
-- Both CHECKs are added NOT VALID and then validated: validation only reads existing rows, all of which satisfy them.
-- Idempotent: re-running drops and re-adds the same two named constraints.
BEGIN;
DO $$
DECLARE
    c record;
BEGIN
    IF to_regclass('market_quotes_extended') IS NULL THEN
        RAISE EXCEPTION 'market_quotes_extended absent: apply migrations/2026_10_31_market_quotes_extended.sql first';
    END IF;
    -- #2384 declared the session CHECK inline, so Postgres named it; find every CHECK on the table that tests session
    -- (and only those) instead of trusting a generated name.
    FOR c IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'market_quotes_extended'::regclass AND contype = 'c'
          AND pg_get_constraintdef(oid) ~ '\msession\M'
          AND conname <> 'market_quotes_extended_reference_ck'
    LOOP
        EXECUTE format('ALTER TABLE market_quotes_extended DROP CONSTRAINT %I', c.conname);
    END LOOP;
END $$;
ALTER TABLE market_quotes_extended DROP CONSTRAINT IF EXISTS market_quotes_extended_reference_ck;
ALTER TABLE market_quotes_extended
    ADD CONSTRAINT market_quotes_extended_session_check
    CHECK (session IN ('premarket', 'afterhours', 'overnight', 'futures_open')) NOT VALID;
ALTER TABLE market_quotes_extended
    ALTER COLUMN reference_close DROP NOT NULL,
    ALTER COLUMN reference_date DROP NOT NULL,
    ALTER COLUMN change_pct DROP NOT NULL;
ALTER TABLE market_quotes_extended
    ADD CONSTRAINT market_quotes_extended_reference_ck
    CHECK (
        (reference_close IS NOT NULL AND reference_date IS NOT NULL AND change_pct IS NOT NULL)
        OR (session IN ('overnight', 'futures_open')
            AND reference_close IS NULL AND reference_date IS NULL AND change_pct IS NULL)
    ) NOT VALID;
ALTER TABLE market_quotes_extended VALIDATE CONSTRAINT market_quotes_extended_session_check;
ALTER TABLE market_quotes_extended VALIDATE CONSTRAINT market_quotes_extended_reference_ck;
COMMIT;
