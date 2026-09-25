-- Rollback for 2026_09_24_event_lineage_columns.sql.
-- Columns are retained by default (evidence preservation, AGENTS.md §0.6).

-- SAFE ROLLBACK: drop the indexes only.
DROP INDEX IF EXISTS operator_conversation_turns_event_idx;
DROP INDEX IF EXISTS operator_conversation_turns_causation_idx;

-- FULL REVERT ONLY — uncomment to drop the added columns:
-- ALTER TABLE operator_conversation_turns
--     DROP COLUMN IF EXISTS event_id,
--     DROP COLUMN IF EXISTS causation_id,
--     DROP COLUMN IF EXISTS parent_event_id;
