# Route and Schema Map

Status:      ACTIVE
as_of:       2026-07-29T12:56:50-04:00
Measured at: efcc51365 / not measured

Typed logical destinations:

- `CRITICAL_OPERATIONS`
- `APPROVALS_ONLY`

Approval allowlist:

- `live_order_2fa_required`
- `live_session_2fa_required`
- `protective_order_approval_required`
- `material_live_authorization_amendment_required`

Core modules:

- `scripts/operator_alert_policy_v2.py`: typed taxonomy, compatibility classifier, fingerprints, incident IDs, route decisions
- `scripts/alert_outbox.py`: event/outbox writes, dedupe, digest queue, delivery audit, settings API helpers
- `scripts/telegram_transport.py`: only allowed low-level Bot API transport endpoint
- `scripts/notification_url_builder.py`: canonical `/v3` URLs, alert deeplink, sanitization/redaction

Migrations:

- Up: `migrations/2026_07_28_alert_notification_outbox.sql`
- Down: `migrations/2026_07_28_alert_notification_outbox.down.sql`

Tables/views:

- `alert_notification_events`
- `alert_notification_deliveries`
- `alert_digest_queue`
- `operator_alert_preferences`
- `operator_alert_preference_audit`
- `v_active_command_center_alerts`

Route modes:

- `IMMEDIATE`
- `DIGEST`
- `COMMAND_CENTER`
- `LOG`

Digest buckets:

- `RISK`
- `TRADING`
- `OPS`

API routes:

- `GET /api/v3/alerts/active`
- `GET /api/v3/alerts/settings`
- `GET /api/v3/alerts/settings/preview`
- `POST /api/v3/alerts/settings`
- `POST /api/v3/alerts/test-send`

UI route/component:

- Existing `/v3/reports` route preserved.
- Added `apps/command-center-v3/src/components/reports/AlertSettingsModal.tsx`.
- Added an Alert Settings button in `apps/command-center-v3/src/pages/ReportsHub.tsx`.
