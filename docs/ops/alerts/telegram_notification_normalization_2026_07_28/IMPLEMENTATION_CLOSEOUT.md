# Implementation Closeout

START SHA: `a51ddd72f75b9fbe5dac749bc786396c9b558104`

END SHA: `a51ddd72f75b9fbe5dac749bc786396c9b558104` (no commit possible; `.git` refs are read-only in this sandbox)

BRANCH: `main` locally; requested `feat/telegram-notification-normalization` could not be created due read-only `.git`.

FILES CHANGED:

- Alert policy/config: `config/operator_alert_policy.yaml`
- Migrations: `migrations/2026_07_28_alert_notification_outbox.sql`, `migrations/2026_07_28_alert_notification_outbox.down.sql`
- Core notification modules: `scripts/operator_alert_policy_v2.py`, `scripts/alert_outbox.py`, `scripts/telegram_transport.py`, `scripts/evaluate_telegram_notification_normalization.py`
- Existing chokepoints/routes: `scripts/telegram_alert.py`, `scripts/telegram_alert_router.py`, `scripts/notification_url_builder.py`, `scripts/api_v2.py`
- UI: `apps/command-center-v3/src/pages/ReportsHub.tsx`, `apps/command-center-v3/src/components/reports/AlertSettingsModal.tsx`
- Tests: `tests/test_telegram_notification_normalization.py`, `tests/test_alert_fatigue_1_routing.py`, `tests/test_telegram_alert_router_jun25.py`
- Legacy sender endpoint literals centralized across the files listed in `SENDER_MIGRATION_MANIFEST.json`

Unrelated pre-existing local change preserved:

- `config/ipo_lockups.json`

MIGRATIONS:

- Up: `migrations/2026_07_28_alert_notification_outbox.sql`
- Down: `migrations/2026_07_28_alert_notification_outbox.down.sql`

API ROUTES:

- `GET /api/v3/alerts/active`
- `GET /api/v3/alerts/settings`
- `GET /api/v3/alerts/settings/preview`
- `POST /api/v3/alerts/settings`
- `POST /api/v3/alerts/test-send`

UI ROUTES/COMPONENTS:

- Existing `/v3/reports` preserved.
- Added `AlertSettingsModal` under Reports.

SENDERS MIGRATED:

- Central semantic sender: `scripts/telegram_alert.py` now publishes through `alert_outbox`.
- Shell direct senders now call central `send_telegram`.
- Application raw endpoint literals removed; only `scripts/telegram_transport.py` contains the Bot API `sendMessage` endpoint.

DIRECT SENDERS REMAINING:

- Endpoint literal remaining: `scripts/telegram_transport.py`
- Residual risk: some legacy Python producers still call requests/urllib with the transport constant and should be converted to typed `publish_event()` calls in the next cleanup pass.

TESTS:

- `25 passed` for focused routing/normalization suite.
- Python compile check passed for changed scripts.

BUILD:

- `apps/command-center-v3` build passed.
- Existing Vite large chunk warning remains.

PROJECTED SEVEN-DAY ROUTING RESULTS:

- Rows: 3,586
- Immediate raw candidates: 19
- Correlated immediate incidents: 9
- Digest: 1,762
- Dashboard-only: 1,801
- Log-only: 4
- Duplicate suppression: 1,543
- Cross-channel duplicate count: 0
- Approval Telegram events: 6
- Approval events with live authorization: 6
- Paper to approvals: 0
- URL violations after sanitize: 0

FEATURE FLAGS:

- `telegram_normalization.runtime_enabled: false`
- Live rollout not activated.

DEPLOYED: NO

REAL TELEGRAM SENT: NO

REAL ORDER ACTION: NO

REAL 2FA REQUESTED: NO

PRODUCTION SECRET READ: NO

ROLLBACK:

- See `ROLLBACK.md`.

OPEN RISKS:

- `.git` write access prevented branch creation, commit, push, and draft PR.
- Legacy Python senders should be fully migrated from transport-constant usage to typed outbox events.
- Migration was authored and compile/test checked but not applied to a live database in this run.
