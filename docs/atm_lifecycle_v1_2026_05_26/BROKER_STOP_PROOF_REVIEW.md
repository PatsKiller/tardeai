# Broker Stop Proof Review

**Total open positions:** 29
**With DB stop:** 27
**Missing DB stop:** 2
**Broker stop proof:** Not yet implemented (Alpaca API read not wired)

## Position Stop Status

| Symbol | Strategy | Trade ID | DB Stop | Broker Proof | Status |
|--------|----------|----------|---------|-------------|--------|
| CMCSA | dividend_growth_compounder | 33 | $23.61 | unavailable | ok |
| CMCSA | dividend_growth_compounder | 32 | $23.61 | unavailable | ok |
| AGNC | reit_income | 31 | $9.71 | unavailable | ok |
| AGNC | reit_income | 30 | $9.71 | unavailable | ok |
| NWG | dividend_growth_compounder | 28 | $15.05 | unavailable | ok |
| ASPN | swing_trade | 27 | $5.15 | unavailable | ok |
| ASPN | swing_trade | 26 | $5.15 | unavailable | ok |
| FLYW | dividend_growth_compounder | 24 | $15.48 | unavailable | ok |
| GCTS | momentum_scalp | 23 | **MISSING** | unavailable | MISSING_STOP |
| GCTS | momentum_scalp | 22 | $1.42 | unavailable | ok |
| INFU | earnings_catalyst | 21 | $7.97 | unavailable | ok |
| GCTS | momentum_scalp | 20 | $1.42 | unavailable | ok |
| FLYW | momentum_scalp | 19 | **MISSING** | unavailable | MISSING_STOP |
| FLYW | swing_breakout | 18 | $16.63 | unavailable | ok |
| FLYW | swing_breakout | 17 | $16.63 | unavailable | ok |
| BLBD | earnings_catalyst | 16 | $76.23 | unavailable | ok |
| BLBD | earnings_catalyst | 15 | $76.23 | unavailable | ok |
| FLYW | swing_trade | 12 | $16.63 | unavailable | ok |
| FLYW | swing_trade | 11 | $16.63 | unavailable | ok |
| FLYW | swing_trade | 10 | $16.63 | unavailable | ok |
| INFU | earnings_catalyst | 9 | $7.97 | unavailable | ok |
| INFU | swing_breakout | 8 | $7.97 | unavailable | ok |
| INFU | swing_breakout | 7 | $7.97 | unavailable | ok |
| EVC | screener | 6 | $7.31 | unavailable | ok |
| XMTR | swing_breakout | 5 | $72.49 | unavailable | ok |
| EVC | screener | 4 | $7.71 | unavailable | ok |
| XMTR | swing_breakout | 3 | $75.29 | unavailable | ok |
| MNKD | gap_and_go | 2 | $3.38 | unavailable | ok |
| SMX | momentum_scalp | 1 | $1.23 | unavailable | ok |

## Missing Stops

- **GCTS** (momentum_scalp) — trade #23, account ALPACA_PAPER
- **FLYW** (momentum_scalp) — trade #19, account ALPACA_PAPER

## Broker Stop Proof Gap

The Alpaca API is not yet queried for real-time broker stop order verification.
Reconciliation runs 2x/day via alpaca_paper_reconciler. No real-time proof available.

## Do NOT cancel, replace, or submit stop orders in this pass.