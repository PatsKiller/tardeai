# Count Truth Drift Contract Report
Generated: 2026-05-20T15:21:57.996794+00:00

## Contract Table
| Source | Filter | Count | Label |
|--------|--------|-------|-------|
| paper_trades | status = 'closed' | 10 | paper_trades_closed |
| paper_trades | status != 'closed' | 13 | paper_trades_open |
| incubator_universe | active = true | None | incubator_active |
| paper_trade_proposals | status = 'pending' | 0 | proposals_pending |
| config/strategies/*.yaml | excluding schema/shared | 23 | strategy_configs |

## Root Cause
- 1 source(s) failed to query: incubator_active; 1 source(s) returned 0: proposals_pending

## Recommended Fix
- investigate missing/zero sources