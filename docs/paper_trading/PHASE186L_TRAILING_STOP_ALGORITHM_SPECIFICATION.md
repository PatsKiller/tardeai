# Phase 186L: Trailing Stop Algorithm Specification

Status:      HISTORICAL
as_of:       2026-06-02T01:02:56-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02

## Current Algorithm: strategy_trailing_policy v2.3

The trailing stop algorithm **exists** in `scripts/strategy_trailing_policy.py` and is integrated into `scripts/paper_trade_monitor.py`. It has never been triggered in production (0 conversions from 24 trades).

### How It Works

1. Every 5 minutes during market hours, `paper_trade_monitor.py` evaluates each open position
2. For each position, it computes: `R = (current_price - entry_price) / initial_risk`
3. It calls `get_trailing_policy(strategy_id)` to get family-specific tiers
4. It walks tiers in reverse (highest R first) to find the best qualifying tier
5. If a tier qualifies, it computes `new_stop = entry_price + lock_r * initial_risk`
6. Stop can only move UP (tighten), never down
7. If new_stop > current_stop, it replaces the stop order on Alpaca

### Trailing Tiers by Strategy Family

#### Momentum (momentum_scalp, gap_and_go, earnings_catalyst, screener)

| R Threshold | Lock | Description |
|-------------|------|-------------|
| >= 1.0R | 0.0R | Breakeven (stop at entry) |
| >= 1.5R | 0.5R | Lock half-R profit |
| >= 2.0R | 1.0R | Lock 1R profit |
| >= 3.0R | 2.0R | Lock 2R profit |

Time stop: Intraday close at 15:45 ET. After-hours trail: NO.

#### Swing (swing_trade, swing_breakout, fib_retracement_bounce, etc.)

| R Threshold | Lock | Description |
|-------------|------|-------------|
| >= 1.0R | 0.0R | Breakeven |
| >= 1.5R | 0.5R | Lock 0.5R |
| >= 2.0R | 1.0R | Lock 1R |
| >= 3.0R | 2.0R | Lock 2R |

Time stop: Max 21 calendar days. After-hours trail: NO.

#### Income (dividend_growth, reit_income, bond_income, etc.)

| R Threshold | Lock | Description |
|-------------|------|-------------|
| >= 1.5R | 0.0R | Breakeven (wider threshold) |
| >= 2.5R | 0.5R | Lock 0.5R |
| >= 3.5R | 1.0R | Lock 1R |
| >= 5.0R | 2.0R | Lock 2R |

Time stop: Review at 90 days. After-hours trail: NO.

#### Position (core_growth, core_index, defense_thesis, sector_rotation)

| R Threshold | Lock | Description |
|-------------|------|-------------|
| >= 2.0R | 0.0R | Breakeven |
| >= 3.0R | 0.5R | Lock 0.5R |
| >= 4.0R | 1.5R | Lock 1.5R |
| >= 6.0R | 3.0R | Lock 3R |

Time stop: Review at 180 days. After-hours trail: NO.

### Trigger Criteria

The algorithm is triggered by:
- **R multiple threshold**: The ONLY current trigger. When price moves favorably enough to cross an R threshold, the stop moves up.

### NOT Triggered By (but should be considered)

| Factor | Current | Recommended |
|--------|---------|-------------|
| ATR | NOT USED | Consider ATR-based trailing for volatile stocks |
| MFE | NOT USED | Consider MFE-based lock (e.g., lock 50% of MFE) |
| Price structure | NOT USED | Consider support/resistance levels |
| Time in trade | NOT USED | Consider time decay tightening |
| Catalyst decay | NOT USED | Consider loosening after catalyst fades |
| Trend confirmation | NOT USED | Consider ADX/moving average trend |
| Volatility regime | NOT USED | Consider wider stops in high-VIX |

### Logging

Every stop adjustment is logged to:
- `paper_trade_risk_actions` table (action_type, old_value, new_value, trigger_reason)
- `stop_change_audit` table (via `stop_change_audit.py`)
- `agent_curation_events` table (MONITOR_ADJUST_STOP event)

### Paper-Only Shadow Test Design

To test trailing effectiveness without changing behavior:

1. Run algorithm against all historical trades
2. For each trade, compute: what would the trailing stop have been at each price point?
3. Compare actual exit vs theoretical trailing exit
4. Metrics:
   - Trades where trailing would have improved outcome
   - Trades where trailing would have hurt outcome (gave back profit)
   - Average R improvement/degradation
   - MFE capture improvement

### Recommendations

1. **More data needed**: 0 trailing activations from 24 trades — no conclusions possible
2. **Lower thresholds for paper testing**: Consider reducing momentum breakeven to 0.5R instead of 1.0R to generate more trailing data
3. **Add MFE-based trailing**: Lock 50-65% of MFE as a complementary trigger
4. **Enable after-hours trailing for swing/income**: These hold multi-day and should be trailed regardless of session
5. **Shadow mode first**: Run parallel trailing calculations without executing, compare to actual outcomes
