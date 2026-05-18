# SP-2B Test Results

**Date:** 2026-05-18

## SP-2B Tests: 17/17 PASS

## Regression: SP-2 16/16 PASS, PP-UX-2 21/21 PASS

## Report Results

- Root cause: confirmed (neither proposal generator calls store_setup_matches)
- Backfill dry-run: 74 proposals, 46 mismatches, 2 skipped (insufficient data)
- Invalid strategy: 6 proposals with strategy_id='screener'
- Config drift: 3 drifted (gap_and_go, momentum_scalp, swing_breakout proposal hash drift)
