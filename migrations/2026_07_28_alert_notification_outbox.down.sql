-- Down migration for the occurrence-based notification outbox.
-- Drops only objects this feature created. Touches no broker, order, 2FA,
-- guardrail, portfolio or holdings table.
--
-- Order matters: views first (alert_notification_events is now a VIEW over the
-- occurrence tables, and DROP TABLE would not remove it), then children before
-- parents rather than relying on FK cascade for correctness.

DROP VIEW IF EXISTS v_active_command_center_alerts;
DROP VIEW IF EXISTS alert_notification_events;

DROP TABLE IF EXISTS alert_digest_queue;
DROP TABLE IF EXISTS alert_notification_deliveries;
DROP TABLE IF EXISTS alert_occurrences;
DROP TABLE IF EXISTS alert_incidents;

DROP TABLE IF EXISTS operator_alert_preference_audit;
DROP TABLE IF EXISTS operator_alert_preferences;

-- Legacy table from the first draft, in case a database still carries it.
DROP TABLE IF EXISTS alert_notification_events;
