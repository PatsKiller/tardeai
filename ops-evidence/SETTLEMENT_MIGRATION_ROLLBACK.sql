-- SETTLEMENT_MIGRATION_ROLLBACK.sql
-- Rollback for migrations/2026_09_07_communication_event_v2_settlement.sql
-- (CommunicationEvent@v2 provider settlement identity — SFR-B-003, defect 6).
--
-- SAFE ROLLBACK (default): drop indexes + check constraints only. Columns are
-- retained so settlement evidence is never destroyed (AGENTS.md §0.6). The
-- migration is forward-only; the UPDATE that stamped legacy rows as
-- UNKNOWN_LEGACY is a statement of fact and is NOT reverted (reverting it would
-- re-introduce invented-history ambiguity, which the migration exists to remove).
--
-- FULL REVERT (optional, clearly marked below): also drop the added columns.
-- This is the ONLY correct order: constraints/indexes before columns.

BEGIN;

-- 1. Indexes (drop before their columns).
DROP INDEX IF EXISTS communication_events_provider_msg_uq;
DROP INDEX IF EXISTS communication_events_settlement_idx;

-- 2. Check constraints (drop before their columns).
ALTER TABLE communication_events DROP CONSTRAINT IF EXISTS communication_events_delivery_owner_ck;
ALTER TABLE communication_events DROP CONSTRAINT IF EXISTS communication_events_settlement_state_ck;

-- 3. FULL REVERT ONLY — uncomment to drop the added columns. Do NOT run this
--    on a ledger that may hold live settlement evidence.
-- ALTER TABLE communication_events
--     DROP COLUMN IF EXISTS provider_message_id,
--     DROP COLUMN IF EXISTS provider_settled_at,
--     DROP COLUMN IF EXISTS provider_settlement_state,
--     DROP COLUMN IF EXISTS delivery_owner,
--     DROP COLUMN IF EXISTS gateway_mode_at_dispatch,
--     DROP COLUMN IF EXISTS curation_kind,
--     DROP COLUMN IF EXISTS curation_provenance,
--     DROP COLUMN IF EXISTS subject_guid;
-- -- thread_id and correlation_id were pre-existing ledger columns; never drop them.

COMMIT;

-- Post-rollback verification:
--   SELECT column_name FROM information_schema.columns
--    WHERE table_name='communication_events'
--      AND column_name IN ('provider_message_id','provider_settled_at',
--          'provider_settlement_state','delivery_owner','gateway_mode_at_dispatch',
--          'curation_kind','curation_provenance','subject_guid');
-- Expected after SAFE ROLLBACK: columns still present, constraints/indexes gone.
