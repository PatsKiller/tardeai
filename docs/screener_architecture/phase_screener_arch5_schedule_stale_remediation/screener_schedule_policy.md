# SCREENER-ARCH-5 — Schedule Policy

Status:      ACTIVE
as_of:       2026-05-19T19:29:16-04:00
Measured at: efcc51365 / not measured

## Current Coverage

27 active screeners across 5 session types:

| Session | Screeners | Cron Coverage |
|---------|-----------|---------------|
| intraday | 5 (daily/daily_1000_1600) | 07:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00 |
| after_close | 1 (daily_1600) | 16:00 |
| weekly | 11 | Part of regular daily runs |
| biweekly | 4 | Part of regular daily runs |
| monthly | 4 | Part of regular daily runs |

## Coverage Gaps

1. **No dedicated premarket session** (04:30-07:00) — current earliest is 07:00
2. **No dedicated overnight session** (20:00+) — fundamentals/catalysts refresh

These are acceptable for current paper-trading phase. The 07:00 and 08:00 runs catch premarket data.

## Schedule Rules

- Every active screener must have a schedule (all 27 do)
- No orphaned screeners (0 found)
- Stale threshold: daily=24h, weekly=8d, biweekly=16d, monthly=35d
- Stale screeners trigger P1 alert (P0 only if 3+ daily screeners stale)
- Success logs go P3 (log only, no Telegram)
- Route through OPS-HYGIENE-1 alert router

## Existing Cron (already installed)

finviz_screener_runner: 07:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00 (7x/day M-F)
trade_ai_orchestrator: 12:00, 14:00, 16:00, 17:30 (4x/day M-F)

No new cron entries needed — coverage is comprehensive.
