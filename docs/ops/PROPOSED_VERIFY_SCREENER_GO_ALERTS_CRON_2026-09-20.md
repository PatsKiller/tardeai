# PROPOSED — operator decision required (AGENTS.md §9.3 / §17)

```
Status: PROPOSED
Effective-Date: PENDING
as_of: 2026-09-20T11:59:00-04:00
Measured at: config/lane_registry.json lane screener-go-alerts ACTIVE; organic stance hunt (Sunday) could not read live crontab (no cron grant)
Canonical repo path: docs/ops/PROPOSED_VERIFY_SCREENER_GO_ALERTS_CRON_2026-09-20.md
Authority: propose-and-stop — installing or editing a crontab line is operator-only
Subject: Verify screener_go_alerts is installed on the live Mon–Fri crontab (organic stance path)
See also: PARTIAL-telegram-CIO-stance; ORGANIC_HOLD_CALLERS; scripts/screener_go_alerts.py
```

## Finding

`PARTIAL-telegram-CIO-stance` closes only when a live producer records
`source=check_investment_send` with `caller` ∈
`{screener_go_alerts, social_scalp_scanner, send_telegram_proposal_alert}`.

Lane registry declares:

```
*/15 9-16 * * 1-5 … screener_go_alerts.py --send
```

A Sunday organic-stance hunt reported that expression as **ACTIVE in the registry**
but **absent from a crontab snapshot** available without a live `crontab -l` grant.
`social_scalp_scanner` and `send_telegram_proposal_alert` remain declared Mon–Fri and
are sufficient for organic OBSERVED if they fire a hold — but losing the GO path
narrows the Monday observe window.

Agents must **not** edit the live crontab. This file proposes verification only.

## Exact operator decision ask

Reply with one of:

1. **CONFIRM_SCREENER_GO_INSTALLED** — live crontab already carries the
   `screener_go_alerts.py --send` Mon–Fri line matching the lane registry
   (`*/15 9-16 * * 1-5` or equivalent). Quote the line.
2. **APPROVE_INSTALL_SCREENER_GO_CRON** — operator (or granted `cron` scope) installs
   the lane registry expression into the live crontab + confirms
   `lane_registry` / `check_lane_registry.py` stay green.
3. **DEFER** — rely on `social_scalp_scanner` + `send_telegram_proposal_alert` alone
   for organic stance proof; leave GO path unverified.
4. **REJECT** — retire or keep GO lane dark deliberately; update ledger reason.

## Why not auto-close

§9.3 / §17 — scheduler install is operator-only. No crontab mutation was made.
Organic stance itself remains schedule-bound until a real Mon–Fri hold lands.
