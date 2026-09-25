-- Additive options identity columns on proposal_outcome_chain (Slice A).
-- Never invents PnL. GUIDs are attribution keys only.
-- Safe to re-run (IF NOT EXISTS). ACCESS EXCLUSIVE briefly — run off-peak.

BEGIN;

ALTER TABLE proposal_outcome_chain
    ADD COLUMN IF NOT EXISTS option_strategy_guid text,
    ADD COLUMN IF NOT EXISTS contract_guid text;

CREATE INDEX IF NOT EXISTS idx_poc_option_strategy_guid
    ON proposal_outcome_chain (option_strategy_guid)
    WHERE option_strategy_guid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_poc_contract_guid
    ON proposal_outcome_chain (contract_guid)
    WHERE contract_guid IS NOT NULL;

COMMIT;
