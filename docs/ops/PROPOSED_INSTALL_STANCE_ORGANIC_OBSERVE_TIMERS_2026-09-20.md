# CONFIRMED — host timers installed (AGENTS.md §9.3 overnight maturity cron grant)

```
Status: CONFIRMED / SUPERSEDES PROPOSED
Effective-Date: 2026-09-20
as_of: 2026-09-20T13:12:00-04:00
Measured at: systemctl --user list-timers tradeai-stance-organic-observe*
Canonical repo path: docs/ops/PROPOSED_INSTALL_STANCE_ORGANIC_OBSERVE_TIMERS_2026-09-20.md
Authority: overnight maturity campaign `cron` grant — CURRENT-resolving maturity schedules only
Subject: stance organic observe timers INSTALLED Mon–Fri 06:35 + 09:05 ET
See also: PARTIAL-telegram-CIO-stance; lane tradeai-stance-organic-observe*
```

## Operator decision

**APPROVE_INSTALL_STANCE_ORGANIC_OBSERVE_TIMERS** — applied under active overnight
`cron` grant (inspect/install/verify CURRENT-resolving maturity schedules). Units point at
`WorkingDirectory=…/portfolio-server/CURRENT`.

## [VERIFIED] host timers

```
Mon 2026-09-21 06:35 ET  tradeai-stance-organic-observe-early.timer → observe.service
Mon 2026-09-21 09:05 ET  tradeai-stance-organic-observe.timer → observe.service
Hand start: Result=success ExecMainStatus=2 (PARTIAL organic=0 — Sunday expected)
```

## Residual

Organic OBSERVED still requires a natural Mon–Fri hold
(`source=check_investment_send` + ORGANIC_HOLD_CALLERS). Timers only remasure.
