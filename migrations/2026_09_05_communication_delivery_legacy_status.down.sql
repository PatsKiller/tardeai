-- Down migration: restore the 11-status CHECK (LEGACY_DELIVERED removed).
ALTER TABLE communication_deliveries
    DROP CONSTRAINT IF EXISTS communication_deliveries_status_check;

ALTER TABLE communication_deliveries
    ADD CONSTRAINT communication_deliveries_status_check
        CHECK (status IN (
            'RESERVED', 'SENDING', 'SENT', 'DELIVERED',
            'ACKNOWLEDGED', 'FAILED', 'BOUNCED', 'SUPPRESSED',
            'EXPIRED', 'CANCELLED', 'UNKNOWN'
        ));
