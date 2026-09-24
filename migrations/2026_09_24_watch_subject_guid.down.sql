-- Rollback for 2026_09_24_watch_subject_guid.sql.
-- Columns are retained by default (evidence preservation, AGENTS.md §0.6).

-- SAFE ROLLBACK: drop the indexes only.
DROP INDEX IF EXISTS watch_directives_subject_guid_idx;
DROP INDEX IF EXISTS watchlist_items_subject_guid_idx;

-- FULL REVERT ONLY — uncomment to drop the added columns:
-- ALTER TABLE watch_directives
--     DROP COLUMN IF EXISTS subject_guid,
--     DROP COLUMN IF EXISTS issuer_guid;
-- ALTER TABLE watchlist_items
--     DROP COLUMN IF EXISTS subject_guid,
--     DROP COLUMN IF EXISTS issuer_guid;
