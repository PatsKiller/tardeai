# B-1C Preflight

**Date:** 2026-05-18 10:00 AM ET
**Safety:** ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true, holdings=$1,194,646

## Bucket System Discovery

Three-tier freshness classification per strategy YAML:

| Bucket | TTL | Watchpool | Strategies |
|--------|-----|-----------|------------|
| SAME_DAY | 4h | No | momentum_scalp, gap_and_go |
| MULTI_DAY | 5-20d | Yes | swing_breakout, swing_trade, earnings_post_momentum, recovery_watch, fib_retracement_bounce, speculative_growth, sector_rotation |
| LONG_CYCLE | 30-90d | Yes (future) | core_index, dividend_growth_compounder, etc. |

## B-1C Weekend Checkpoint (May 16)

- 5 Bucket 2 strategies enabled: swing_breakout, swing_trade, earnings_post_momentum, recovery_watch, fib_retracement_bounce
- All have watchpool=true, rollback_to_legacy=false
- Classifier health cron fires daily 07:55 ET
- Rollback API available: POST /api/v2/strategy-configs/{id}/freshness

## Current Watchpool State

- 1 row: DWSN speculative_growth (entered today 4:08 AM, MULTI_DAY, expires May 28)
- Watchpool is working — first entry populated from today's pre-market scan

## Momentum Scalp Boundary

- `momentum_scalp` YAML: bucket=SAME_DAY, watchpool=false, ttl_hours=4
- momentum_scalp is a valid Trade AI YAML strategy (not the separate daily scalp workflow)
- 30 proposals in paper_trade_proposals with strategy_id='momentum_scalp'
- These are Trade AI proposals, NOT separate daily scalp records
- No evidence of separate "TradeAI daily momentum scalp" records in paper_trade_proposals

## DB Sync Status

- YAML configs: freshness blocks present on all 9 Bucket 2 strategies
- DB strategy_registry: 3 strategies missing (earnings_post_momentum, earnings_pre_buildup, fib_retracement_bounce)
- Config hash drift present (YAML updated May 15, DB synced May 7)
