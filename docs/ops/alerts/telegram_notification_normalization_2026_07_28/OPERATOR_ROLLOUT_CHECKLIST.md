# Operator Rollout Checklist

Preflight:

- Confirm migration can apply and rollback on lab PostgreSQL.
- Confirm `TELEGRAM_BOT_TOKEN`, `TRADEAI_GENERAL_ALERT_CHAT_ID`, and `TRADEAI_PROPOSAL_ALERT_CHAT_ID` are secret-backed and not stored in preference rows.
- Confirm no production broker credentials are mounted for test replay.
- Confirm `/v3/reports` and `/v3/system` regression checks pass.
- Confirm direct sendMessage guard passes with only `scripts/telegram_transport.py` allowed.

Rollout:

1. Apply additive migration.
2. Load Alert Settings in `/v3/reports`.
3. Review seven-day projected volume before saving changes.
4. Keep `telegram_normalization.runtime_enabled` OFF until operator approval.
5. Run synthetic test events only; verify they are visibly labeled.
6. Enable digest scheduler for 08:45 ET risk and 17:55 ET ops/trading after queue validation.
7. Enable immediate delivery only after verifying approval allowlist and critical operations channel secrets.

Post-rollout verification:

- Approval Telegram has zero paper proposals.
- 100% Approval Telegram events have live authorization references.
- P1 events appear in digest queue, not individual sends.
- Active alerts older than seven days do not appear in Command Center active projection.
- Redaction violations after sanitize remain zero.
