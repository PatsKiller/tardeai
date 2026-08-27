# A-5 Strategy Categorization — 2026-05-15

## Pipeline Validation: PASSED
- Pre-A4 (May 14): 0 signals at all daytime runs
- Post-A4 (May 15): 5 signals at each run, 12 proposals created
- First time in bot's history that daytime runs produce proposals

## Categorization

### WORKING_PRODUCING (6 strategies — has trades)
| Strategy | Trades | Closed | W/L | P&L | Status |
|----------|--------|--------|-----|-----|--------|
| swing_breakout | 7 | 2 | 1/0 | +$67.83 | TOO_FEW but positive |
| momentum_scalp | 5 | 3 | 0/3 | -$21.76 | LOSING — stop_too_tight pattern |
| earnings_catalyst | 4 | 1 | 0/1 | -$407.60 | LOSING — investigate |
| swing_trade | 3 | 1 | 0/1 | -$15.39 | TOO_FEW |
| gap_and_go | 1 | 0 | - | $0 | TOO_FEW |
| dividend_growth_compounder | 1 | 1 | 1/0 | +$29.07 | TOO_FEW but positive |

### PROPOSALS_BUT_NO_TRADES (4 — approval bottleneck)
| Strategy | Proposals | Today | Issue |
|----------|-----------|-------|-------|
| speculative_growth | 6 | 1 | 3 expired, 3 rejected |
| recovery_watch | 5 | 4 | 4 rejected, 1 pending NOW |
| sector_rotation | 2 | 0 | Both expired |
| core_growth_compounder | 1 | 0 | Expired |

### SIGNALS_NO_PROPOSALS (10 — pre-B1a inflated signals, will clean up)
income_add, tax_loss_harvest, cash_or_stable, high_yield_income_bdc,
reit_income, international_dividend, fib_retracement_bounce,
earnings_post_momentum, defense_thesis, earnings_pre_buildup

These have signals from the pre-B1a classifier bug. MLGO/RCEL mapped to
all of them. Next signal generation run with the fixed signal_sync will
produce cleaner data.

### NO_SIGNALS (3)
bond_income, core_index, covered_call_income — no signals generated.
These strategies' screen_filters may be too restrictive for the current
scan population.

## Key Finding
The primary bottleneck is NOT pipeline or classification. It's APPROVAL
BANDWIDTH. The 4 strategies in PROPOSALS_BUT_NO_TRADES are generating
valid proposals that expire in 3 days without operator action.
