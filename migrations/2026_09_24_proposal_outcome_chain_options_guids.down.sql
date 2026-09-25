-- Rollback for 2026_09_24_proposal_outcome_chain_options_guids.sql.
-- Columns are retained by default (evidence preservation, AGENTS.md §0.6).

-- SAFE ROLLBACK: drop the partial indexes only.
DROP INDEX IF EXISTS idx_poc_option_strategy_guid;
DROP INDEX IF EXISTS idx_poc_contract_guid;

-- FULL REVERT ONLY — uncomment to drop the added columns:
-- ALTER TABLE proposal_outcome_chain
--     DROP COLUMN IF EXISTS option_strategy_guid,
--     DROP COLUMN IF EXISTS contract_guid;
