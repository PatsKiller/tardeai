-- FQ-143 / D32 §6: per-channel delivery receipts for the CRITICAL tier.
--
-- alert_notification_deliveries already records one row per attempt, but it cannot say WHICH channel an attempt was for:
-- it has logical_destination (a routing destination) and telegram_message_id (a Telegram receipt). D32 §6 requires a
-- receipt for every channel -- the Telegram Critical chat, email, and the operator's email-to-text gateway -- so an
-- operator-facing page can say which of the three actually went.
--
-- Additive and nullable throughout: existing rows keep working, and no row is rewritten. `channel` is deliberately NOT a
-- foreign key or an enum: the channel vocabulary belongs to the code that sends (critical_channels.CHANNELS), and a
-- database enum would need a migration every time a channel is added.

ALTER TABLE alert_notification_deliveries
    ADD COLUMN IF NOT EXISTS channel TEXT;

ALTER TABLE alert_notification_deliveries
    ADD COLUMN IF NOT EXISTS provider_receipt TEXT;

-- Backfill the one channel that existed before this column: every historical delivery row was a Telegram attempt.
UPDATE alert_notification_deliveries SET channel = 'telegram' WHERE channel IS NULL;

COMMENT ON COLUMN alert_notification_deliveries.channel IS
    'Which channel this attempt was for: telegram / telegram_critical / email / text_gateway. NULL means a row written before 2026-11-05.';
COMMENT ON COLUMN alert_notification_deliveries.provider_receipt IS
    'The provider''s own identifier for this send (Gmail message id, SMTP queue id). Telegram keeps using telegram_message_id.';

CREATE INDEX IF NOT EXISTS alert_deliveries_by_channel_idx
    ON alert_notification_deliveries (channel, created_at);
