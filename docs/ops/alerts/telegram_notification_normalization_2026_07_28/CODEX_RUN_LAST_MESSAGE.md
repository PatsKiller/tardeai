Implemented the notification-normalization foundation and wrote the required artifacts under:

`docs/ops/alerts/telegram_notification_normalization_2026_07_28/`

Key outcomes:
- Added typed alert policy, logical channels, approval allowlist, digest routing, TTLs, redaction, alert deeplinks, and durable outbox schema.
- Wired `send_telegram()` through the normalized outbox path; `bypass_router=True` is now recorded metadata, not an escape hatch.
- Added `/api/v3/alerts/*` settings/active-alert endpoints and an additive Reports alert-settings modal.
- Added replay evaluator and tests using the seven-day/full CSV fixtures.
- Removed raw `sendMessage` endpoint literals from application files; only `scripts/telegram_transport.py` contains the low-level endpoint literal.

Verification:
- `.venv/bin/python -m pytest tests/test_alert_fatigue_1_routing.py tests/test_telegram_alert_router_jun25.py tests/test_telegram_notification_normalization.py -q` → `25 passed`
- Changed Python scripts compile cleanly.
- `cd apps/command-center-v3 && npm run build` → passed.
- Seven-day replay projection: `9` correlated immediate incidents, `0` paper approvals to approval Telegram, `0` cross-channel duplicates, `0` post-sanitize URL violations.

Important limitation: I could not create the requested branch, commit, push, or open a PR because `.git` refs are read-only in this sandbox. The attempted branch creation failed with a read-only filesystem error. No deployment, real Telegram send, real order action, real 2FA, or production secret read occurred.

Residual risk is documented: some legacy Python senders now use the centralized transport constant but still need full semantic migration to typed `publish_event()` calls in a follow-up pass.