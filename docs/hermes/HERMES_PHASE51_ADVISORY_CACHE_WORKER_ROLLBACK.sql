-- Phase 51 Rollback — revert cache worker changes
BEGIN;
-- Worker only refreshes existing hermes_* sections, so rollback is:
-- 1. Stop timer
-- 2. Events marked 'skipped' remain (harmless)
-- No cache sections were created (section cap enforced)
COMMIT;
