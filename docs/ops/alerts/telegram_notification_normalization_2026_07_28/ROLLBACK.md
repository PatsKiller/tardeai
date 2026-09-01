# Rollback

Status:      ACTIVE
as_of:       2026-07-29T12:56:50-04:00
Measured at: efcc51365 / not measured

No production deployment was performed.

Code rollback:

1. Revert the source changes from this working tree or PR.
2. Restore prior `config/operator_alert_policy.yaml` if needed.
3. Remove additive UI component `AlertSettingsModal.tsx` and `/api/v3/alerts/*` handlers if backing out the feature.

Database rollback:

1. Apply `migrations/2026_07_28_alert_notification_outbox.down.sql`.
2. This drops only additive alert-notification tables and view:
   - `v_active_command_center_alerts`
   - `operator_alert_preference_audit`
   - `operator_alert_preferences`
   - `alert_digest_queue`
   - `alert_notification_deliveries`
   - `alert_notification_events`

Operational rollback:

- Keep live feature flags OFF.
- Do not send synthetic test events to production channels.
- Re-run the direct sender guard after rollback if any sender files are restored.
