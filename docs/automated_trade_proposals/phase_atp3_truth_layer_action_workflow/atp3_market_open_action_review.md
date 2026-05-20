# ATP-3 — Market-Open Action Review

**Time:** 2026-05-20 02:35 ET (overnight — all jobs pending market open)

## Cron Job Status

| Job | Last Ran | Next Fire | Status |
|-----|----------|-----------|--------|
| Stale sweeper (08:15) | May 19 08:25 | May 20 08:15 | Pending |
| Stale sweeper apply (08:25) | May 19 08:25 | May 20 08:25 | Pending |
| Q-1 quote refresh (09:00-15:00) | May 19 15:55 | May 20 09:00 | Pending |
| ATP-2 30-min revalidation (09:00-15:00) | Never | May 20 09:00 | First run |
| ATP-2 premarket 4AM | Never | May 20 04:00 | First run |
| ATP-2 premarket 9AM | Never | May 20 09:00 | First run |

## Current Proposals (all blocked)

| # | Symbol | Strategy | R:R | Quote Age | Verdict | Action |
|---|--------|----------|-----|-----------|---------|--------|
| 102 | INGM | dividend_growth | 2.00 | 8h | UNKNOWN_QUOTE | Refresh at 09:00 — best candidate |
| 101 | SIF | defense_thesis | 2.00 | 278h | UNKNOWN_QUOTE | EXPIRE — 11.6 days stale |
| 100 | NVST | recovery_watch | 2.01 | 301h | UNKNOWN_QUOTE | EXPIRE — 12.5 days stale |
| 99 | CODX | swing_trade | 1.91 | 13h | UNKNOWN_QUOTE | WATCH — R:R below 2.0, RVOL 301x |
| 98 | DOC | reit_income | 1.99 | 317h | UNKNOWN_QUOTE | EXPIRE — 13.2 days stale |

## Why Stale Sweeper Didn't Expire SIF/NVST/DOC

The sweeper uses **proposal age** (created_at), not **quote age**. SIF/NVST/DOC were created by the incubator promoter only ~5-9h ago, so the sweeper sees them as "fresh" proposals even though their underlying quotes are 11-13 days old.

This is a gap: the sweeper should also check quote age or last_price_checked_at, not just proposal creation time.

## Execution-Ready: 0

No proposal is execution-ready. All require:
1. Fresh execution-eligible quote (Alpaca/Polygon, not FinViz/yfinance)
2. Execution readiness check (bid/ask/spread/session)
3. R:R >= 2.0 for CODX and DOC

## What Will Happen Automatically

| Time ET | Job | Expected Result |
|---------|-----|-----------------|
| 04:00 | ATP-2 premarket_4am | Flag high-gap/RVOL movers from overnight data |
| 08:15 | Stale sweeper dry-run | Report proposal staleness (won't catch SIF/NVST/DOC by proposal age) |
| 08:25 | Stale sweeper apply | May expire TLSI if still pending |
| 09:00 | Q-1 quote refresh | Get fresh quotes for INGM, CODX from Alpaca |
| 09:00 | ATP-2 premarket_9am | Final ranking of ready candidates |
| 09:00-09:30 | ATP-2 30-min revalidation | Re-check all 5 proposals |
| 09:35 | Watchpool maturity | Alert on near-trigger candidates |

## Safety

- Trades created: NO
- Orders submitted: NO
- Live trading: NO
- Approval gates: STRENGTHENED (unknown quote blocks, R:R < 2.0 blocks)
