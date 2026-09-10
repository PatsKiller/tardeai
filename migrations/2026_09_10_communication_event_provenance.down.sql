-- Rollback for 2026_09_10_communication_event_provenance.sql.
-- Columns are retained by default (evidence preservation, AGENTS.md §0.6).
-- Full column drop is gated and commented.

-- SAFE ROLLBACK: retain columns (no index/constraint to drop here).
-- No-op: the provenance columns are additive and carry evidence.

-- FULL REVERT ONLY — uncomment to drop the added columns:
-- ALTER TABLE communication_events
--     DROP COLUMN IF EXISTS source_sha,
--     DROP COLUMN IF EXISTS provenance;
