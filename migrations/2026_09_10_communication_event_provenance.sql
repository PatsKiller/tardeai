-- CommunicationEvent@v2 — §2 envelope extras: source SHA + provenance.
-- Grok-closure Phase 3. Additive follow-up to 2026_09_07_communication_event_v2_settlement.sql.
--
-- The durable gateway acceptance contract requires source/build SHA and
-- epoch+trigger provenance on the authoritative event row. `build_sha` already
-- exists on the ledger; `source_sha` and `provenance` exist on the Python
-- CommunicationEvent dataclass (CampaignInterfaces@v1 §2 envelope extras) but not
-- on the table. This migration adds them so the durable row is authoritative for
-- settlement AND provenance. Additive only; no backfill; never edits the shipped
-- settlement migration.

ALTER TABLE communication_events
    ADD COLUMN IF NOT EXISTS source_sha    TEXT,
    ADD COLUMN IF NOT EXISTS provenance    JSONB;
