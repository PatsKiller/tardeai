DROP INDEX IF EXISTS alert_occurrences_message_type_idx;
ALTER TABLE alert_notification_deliveries
    DROP COLUMN IF EXISTS provenance,
    DROP COLUMN IF EXISTS policy_version,
    DROP COLUMN IF EXISTS renderer_version,
    DROP COLUMN IF EXISTS message_type;
ALTER TABLE alert_occurrences
    DROP COLUMN IF EXISTS provenance,
    DROP COLUMN IF EXISTS registry_version,
    DROP COLUMN IF EXISTS message_schema_version,
    DROP COLUMN IF EXISTS message_type;
