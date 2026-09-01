# Operator steps 1–3 (post Phase 13) — executed 2026-08-14

Status:      ACTIVE
as_of:       2026-08-14T08:55:29-04:00
Measured at: efcc51365 / not measured

## 1. Pull request → main

| Item | Value |
| --- | --- |
| PR | https://github.com/PatsKiller/tardeai/pull/299 |
| Head | `wt/cio-phase1-notify` |
| Base | `main` |
| Title | feat(cio): production hardening Phases 0–13 (RC canary live) |

CI follow-ups landed on the PR head for runner green (`requests`, HTML-only hard parity gate, PR merge pin regen).

## 2. Required status check on `main`

Branch protection updated:

| Rule | Setting |
| --- | --- |
| Required status contexts | **`cio-hardening`** |
| Strict (branch up to date) | **true** |
| Force-push | blocked |
| Deletions | blocked |
| PR reviews | dismiss stale; 0 approving required |

Merge to `main` now requires a green `cio-hardening` check on the PR.

## 3. Live Telegram canary

| Item | Result |
| --- | --- |
| Script | `scripts/cio_phase13_telegram_live_canary.py` |
| Delivered | **true** |
| `REAL_TELEGRAM_SENDS` | **1** |
| Channel | `telegram_cio` only |
| `general_channel` | **false** |
| Message id | `24` |
| Decision id | `dec_phase13_live_canary` |
| CIO chats | 3 (suffixes only logged) |
| Bot fingerprint | `d6a3547c3269` (not the token) |

### Host live path

Systemd drop-in `20-exact-sha-release.conf`:

- **Removed** `CIO_TELEGRAM_INTERDICT=1`
- **Added** `EnvironmentFile=-/home/johnclaw/.config/tradeai/cio-telegram.env`
- **Added** `AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1`
- **Added** `CIO_TELEGRAM_CANARY_ENABLE=1`
- Canary approval phrase **not** left permanent in unit (one-shot script only)

Backup: `20-exact-sha-release.conf.bak-before-live-canary-*`

### Re-interdict (if desired)

```bash
# restore interdict in drop-in, remove AUTHORIZE, daemon-reload, restart
# or:
export CIO_TELEGRAM_INTERDICT=1
unset AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY
unset CIO_TELEGRAM_CANARY_APPROVAL
```

## Safety

- No secrets printed
- General Telegram bot **not** used
- Financial authority still **READ_ONLY_ADVISORY**
- Broker / order / stop paths **not** opened
