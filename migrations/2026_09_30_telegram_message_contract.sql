-- Canonical message metadata is additive to the occurrence/delivery outbox.
-- Existing payloads remain the compatibility source when this migration is absent.
ALTER TABLE alert_occurrences
    ADD COLUMN IF NOT EXISTS message_type TEXT,
    ADD COLUMN IF NOT EXISTS message_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS registry_version TEXT,
    ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE alert_notification_deliveries
    ADD COLUMN IF NOT EXISTS message_type TEXT,
    ADD COLUMN IF NOT EXISTS renderer_version TEXT,
    ADD COLUMN IF NOT EXISTS policy_version TEXT,
    ADD COLUMN IF NOT EXISTS provenance JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS alert_occurrences_message_type_idx
    ON alert_occurrences (message_type, observed_at DESC);
