# Deployment NOT authorized

This branch is parallel and isolated. It is NOT deployed and NOT merged.

## Prohibited

- No production deployment, systemd, or cron changes.
- No `CURRENT` symlink change.
- No `.env`, secrets, or credential changes.
- No production holdings / cash / orders / risk-policy writes.
- No Telegram sends.
- No service restarts (portfolio-server, CIO Telegram, SEC ingest).

## Proof

All providers are `READ_ONLY` (asserted by tests). No provider exposes write /
order / stop / broker surfaces. `OPENBB_DECISION = DEFER` (no new dependency).
Production DB writes in this branch = 0; Telegram sends = 0.
