# ATP-3 — Market-Open Readiness Report

**Time:** 2026-05-20 02:30 ET (overnight — market closed)

## Quote Refresh Result

Q-1 ran for 5 targets but no new scan data was produced — expected at this hour. FinViz and Alpaca do not return fresh quotes overnight. The Q-1 cron will re-run automatically at 09:00 ET when market data becomes available.

## Before/After ATP-3

| Metric | Before ATP-3 | After ATP-3 | After Q-1 (overnight) |
|--------|-------------|-------------|----------------------|
| Unknown quote | 0 (hidden) | 5 | 5 (expected overnight) |
| Stale quote | 0 | 0 | 0 |
| Approval allowed | 5 (incorrect!) | 0 | 0 |
| Execution-ready | 0 | 0 | 0 |

## Proposal Status

| # | Symbol | Strategy | Quote Age | R:R | Verdict | Action |
|---|--------|----------|-----------|-----|---------|--------|
| 102 | INGM | dividend_growth | 8.1h | 2.00 | UNKNOWN_QUOTE | Refresh at 09:00, then Check Execution |
| 99 | CODX | swing_trade | 12.8h | 1.91 | UNKNOWN_QUOTE | WATCH at open — RVOL 301x. R:R below minimum, needs wider target |
| 98 | DOC | reit_income | 316.8h | 1.99 | UNKNOWN_QUOTE | **EXPIRE or REBUILD** — 13.2 days stale |
| 101 | SIF | defense_thesis | 277.7h | 2.00 | UNKNOWN_QUOTE | **EXPIRE or REBUILD** — 11.6 days stale |
| 100 | NVST | recovery_watch | 300.5h | 2.00 | UNKNOWN_QUOTE | **EXPIRE or REBUILD** — 12.5 days stale |

## Recommendations

### At Market Open (09:00-09:35 ET)
- **INGM**: Q-1 will refresh quote. If fresh and R:R holds, proceed to Check Execution
- **CODX**: Watch for continuation vs reversal. RVOL 301x is extraordinary. R:R 1.91 needs wider target ($2.40+) or tighter stop to reach 2.0 minimum

### Should Be Expired/Rebuilt
- **SIF** (277h stale): Entry $18.00 likely invalid. Stale proposal sweeper should expire at 08:15
- **NVST** (300h stale): Entry $26.10 likely invalid. Same
- **DOC** (316h stale): Entry $19.50 likely invalid. Same

### Execution-Ready Proposals: 0
No proposal is execution-ready. All require at minimum:
1. Fresh execution-eligible quote
2. Execution readiness check (bid/ask/spread)
3. AI review (recommended)

## Safety
- Trades created: NO
- Orders submitted: NO
- Live trading: NO
- Approval gates: STRENGTHENED (not weakened)
