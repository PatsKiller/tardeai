# Run Type Column Implementation — 2026-05-29

## Source of run_type
- `strategy_backtest_runs.run_type` via LEFT JOIN on `run_id`
- API already returned `run_type` at line 18898 of api_v2.py — no API change needed
- Values: `replay_trades`, `replay_proposals`, `champion` (or NULL for champion sims)

## Files Changed
- `apps/command-center-v2/src/pages/Backtesting.tsx` — 2 edits:
  1. Added 'Source' to table header columns (line 433)
  2. Added Source cell with color-coded badge between Strategy and Date columns

## UI Behavior
| run_type | Badge Label | Color |
|----------|-------------|-------|
| replay_trades | replay | green (#4ade80) |
| replay_proposals | proposal | yellow (#fbbf24) |
| champion / NULL | champion | purple (#a78bfa) |

Each trade row now shows a small colored pill indicating whether it's a real replay, proposal replay, or hypothetical champion simulation.

## API Before/After
No API change — `run_type` was already present in the `/api/v2/backtesting/trades` response at line 18898.

## Validation
- TypeScript: PASS (no type errors)
- Vite build: PASS (309ms)
- API response confirms run_type present for all trades
