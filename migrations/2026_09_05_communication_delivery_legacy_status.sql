-- Trade AI Communications Gateway — add LEGACY_DELIVERED delivery status.
-- Additive only. Does not modify broker/order/2FA/guardrail tables.
--
-- Wave A F1: the gateway auto-reserves a ChannelDelivery stub on every
-- publish. For non-owned classes the legacy path delivers and the stub was
-- never settled, leaving phantom RESERVED rows. This relaxes the status CHECK
-- to admit the terminal LEGACY_DELIVERED state the settlement writes.

ALTER TABLE communication_deliveries
    DROP CONSTRAINT IF EXISTS communication_deliveries_status_check;

ALTER TABLE communication_deliveries
    ADD CONSTRAINT communication_deliveries_status_check
        CHECK (status IN (
            'RESERVED', 'SENDING', 'SENT', 'DELIVERED',
            'ACKNOWLEDGED', 'FAILED', 'BOUNCED', 'SUPPRESSED',
            'EXPIRED', 'CANCELLED', 'UNKNOWN', 'LEGACY_DELIVERED'
        ));
