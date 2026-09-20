# CONFIRMED — live crontab verified (AGENTS.md §9.3)

```
Status: CONFIRMED / SUPERSEDES PROPOSED
Effective-Date: 2026-09-20
as_of: 2026-09-20T12:00:30-04:00
Measured at: crontab -l under active cron grant (maturity overnight campaign)
Canonical repo path: docs/ops/PROPOSED_VERIFY_SCREENER_GO_ALERTS_CRON_2026-09-20.md
Authority: read-only crontab inspect; no install mutation
Subject: screener_go_alerts + peer organic stance producers — INSTALLED on live Mon–Fri crontab
See also: PARTIAL-telegram-CIO-stance; ORGANIC_HOLD_CALLERS
```

## Operator decision

**CONFIRM_SCREENER_GO_INSTALLED** — verified by agent under active `cron` grant
(inspect-only). No crontab edit.

## [VERIFIED] live lines (Mon–Fri)

```
*/2 9-16 * * 1-5 … scripts/send_telegram_proposal_alert.py --mode pending --send
0,30 6-9 * * 1-5 … scripts/social_scalp_scanner.py
*/15 9-16 * * 1-5 … scripts/screener_go_alerts.py --send
  (cwd=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild)
```

All three `ORGANIC_HOLD_CALLERS` have scheduled Mon–Fri paths. Sunday organic=0 is
schedule-bound, not a missing-job defect.

## Residual

Organic OBSERVED still requires a real hold receipt Mon–Fri
(`source=check_investment_send` + organic caller). Observe timers remain armed.
