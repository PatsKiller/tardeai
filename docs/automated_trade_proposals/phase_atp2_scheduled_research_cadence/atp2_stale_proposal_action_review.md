# ATP-2 — Stale Proposal Action Review

**Generated:** 2026-05-20 01:54 ET (overnight)

## Pending Automated Trade Proposals

| # | Symbol | Strategy | Entry | Stop | Age | Quote Age | Status | Action |
|---|--------|----------|-------|------|-----|-----------|--------|--------|
| 102 | INGM | dividend_growth_compounder | $25.45 | $24.18 | 4.9h | 7.5h | needs_quote_refresh | **Refresh at market open** — quote is only 7h old, normal overnight staleness |
| 101 | SIF | defense_thesis | $18.00 | $17.10 | 4.9h | **277h** | needs_quote_refresh | **REBUILD or EXPIRE** — quote is 11.5 days old, price may have moved significantly |
| 100 | NVST | recovery_watch | $26.10 | $24.80 | 7.9h | **300h** | needs_quote_refresh | **REBUILD or EXPIRE** — quote is 12.5 days old, entry/stop likely invalid |
| 99 | CODX | swing_trade | $2.15 | $2.04 | 8.9h | 12.2h | needs_quote_refresh | **MARKET-OPEN WATCH** — RVOL 301x, +57% change, +42% gap. Refresh and evaluate |
| 98 | DOC | reit_income | $19.50 | $18.52 | 8.9h | **316h** | needs_quote_refresh | **REBUILD or EXPIRE** — quote is 13.2 days old, price likely changed |

## Recommendations

### Refresh at Market Open (normal)
- **INGM** (#102): Quote only 7.5h old. Q-1 will refresh at 09:00. Normal overnight gap.
- **CODX** (#99): Quote 12h old but RVOL 301x demands attention. Watch at open for continuation vs reversal.

### Rebuild or Expire (critically stale)
- **SIF** (#101): 277h quote age = 11.5 days stale. Entry $18.00 and stop $17.10 are likely invalid. Should be expired by stale proposal sweeper or manually rebuilt with fresh quote.
- **NVST** (#100): 300h = 12.5 days stale. Same issue.
- **DOC** (#98): 316h = 13.2 days stale. Same issue.

### Why These Weren't Already Expired
The stale proposal sweeper runs at 08:15/08:25 and 15:00/16:10 but these proposals were created today by the incubator promoter. The sweeper's stale threshold may not have caught them yet, or the sweeper uses a different stale definition than "quote age."

## Executable Now?
**NO** — All proposals require market-open execution readiness check before any approval.

## Safety
- Trades created: NO
- Orders submitted: NO
- Proposals approved: NO
- Live trading: NO
