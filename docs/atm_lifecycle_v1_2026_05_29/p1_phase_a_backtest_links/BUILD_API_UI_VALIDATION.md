# Build / API / UI Validation — 2026-05-29

## Python
- `py_compile scripts/api_v2.py` — PASS

## TypeScript
- `npx tsc --noEmit` — PASS (no errors)

## Vite Build
- `npx vite build` — PASS (309ms)
- `Backtesting-DVRHzBGL.js` — 425.81 kB (includes new Source column and Classified KPI)

## API Validation

### /api/v2/backtesting/status
```
classification_total: 3593
classification_classified: 3593
classification_unclassified: 0
classification_pct: 100.0
```
PASS — completeness metric present and correct.

### /api/v2/backtesting/trades?run_type=replay_trades&limit=3
```
APPS     swing_breakout                 run_type=replay_trades
NVDA     dividend_growth_compounder     run_type=replay_trades
APAM     speculative_growth             run_type=replay_trades
```
PASS — run_type present in API response (was already there, no API change needed).

## UI Changes
1. KPI row: 7 cards (was 6). New "Classified" card shows 3,593 / 3,593. Would show red accent if unclassified > 0.
2. Trades table: 9 columns (was 8). New "Source" column shows color-coded badge: green=replay, yellow=proposal, purple=champion.
