# B-1C Scope — Bucket 2 Migration and Scalp Boundary

## Purpose

B-1C validates the Bucket 2 (MULTI_DAY) strategy watchpool migration and enforces
a clean boundary between the Trade AI paper proposal system and any separate daily
momentum scalp workflows.

## What "Bucket 2" Means

Bucket 2 strategies have MULTI_DAY freshness — they track candidates in the
strategy_watchpool table over 5-20 trading days, re-evaluating daily, with
TTL-based expiry. This replaces legacy same-day-only behavior where candidates
were lost if not promoted within hours.

## Bucket 2 Strategies (7 with watchpool=true)

swing_breakout (10d), swing_trade (10d), earnings_post_momentum (5d),
recovery_watch (15d), fib_retracement_bounce (20d), speculative_growth (10d),
sector_rotation (20d)

## Daily Momentum Scalp Boundary

- `momentum_scalp` is a valid Trade AI YAML strategy (SAME_DAY, watchpool=false)
- "TradeAI daily momentum scalps" are a separate operator workflow
- Daily scalps must NOT appear in: Paper Proposals, SP-1/SP-2 strategy proof,
  A-5 observation, incubator promotion, strategy scorecards, Phase 8 scoring
- The Trade AI `momentum_scalp` YAML strategy is valid and should NOT be disabled
- If daily scalp records enter the system via screener/incubator, they must be
  filtered by source/label, NOT by strategy_id='momentum_scalp'

## What B-1C Does

- Validates Bucket 2 watchpool is operational (DWSN already entered)
- Validates YAML freshness configs are consistent
- Audits daily momentum scalp boundary for leakage
- Reports DB sync status (3 missing strategies, hash drift)
- Validates SP-2C route audit for new watchpool-promoted proposals

## What B-1C Does NOT Do

- Does not activate/deactivate strategies
- Does not change YAML thresholds
- Does not auto-optimize screeners
- Does not auto-reassign proposals
- Does not create trades or submit orders
- Does not enable live trading
- Does not run final A-5 or Phase 8D
