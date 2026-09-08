-- Rollback for CommunicationEvent@v2 settlement. Indexes/constraints only;
-- columns retained so settlement evidence is not destroyed (AGENTS.md §0.6).
DROP INDEX IF EXISTS communication_events_provider_msg_uq;
DROP INDEX IF EXISTS communication_events_settlement_idx;
ALTER TABLE communication_events DROP CONSTRAINT IF EXISTS communication_events_delivery_owner_ck;
ALTER TABLE communication_events DROP CONSTRAINT IF EXISTS communication_events_settlement_state_ck;
