-- Reverse of 2026_11_05_critical_delivery_channels.sql.
--
-- Dropping the index first, then the columns. The backfilled channel values go with the column; nothing else in the row
-- is touched, so a rollback loses the channel labelling and nothing else.

DROP INDEX IF EXISTS alert_deliveries_by_channel_idx;

ALTER TABLE alert_notification_deliveries DROP COLUMN IF EXISTS provider_receipt;
ALTER TABLE alert_notification_deliveries DROP COLUMN IF EXISTS channel;
