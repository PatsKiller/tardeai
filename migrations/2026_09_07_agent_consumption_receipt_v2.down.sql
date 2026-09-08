-- Rollback for AgentConsumptionReceipt@v2. Drops only what the up-migration added.
-- Columns are NOT dropped: dropping them would destroy consumption evidence
-- written while @v2 was live (AGENTS.md §0.6). Constraints and indexes only.
DROP INDEX IF EXISTS communication_agent_consumption_receipts_effect_idx;
DROP INDEX IF EXISTS communication_agent_consumption_receipts_wake_idx;
DROP INDEX IF EXISTS communication_agent_consumption_receipts_idem_uq;
DROP INDEX IF EXISTS communication_agent_consumption_receipts_src_uq;
ALTER TABLE communication_agent_consumption_receipts
    DROP CONSTRAINT IF EXISTS communication_agent_consumption_receipts_effect_kind_ck;
ALTER TABLE communication_agent_consumption_receipts
    DROP CONSTRAINT IF EXISTS communication_agent_consumption_receipts_source_kind_ck;
