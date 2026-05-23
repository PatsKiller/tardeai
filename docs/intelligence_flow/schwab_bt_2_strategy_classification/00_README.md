# SCHWAB-BT-2 — Strategy Classification for Historical Trades

**Date:** 2026-05-22

## Results

| Metric | Count |
|--------|-------|
| Total canonical trades | 130 |
| Classified | 87 |
| Unclassifiable (transfers/corporate actions) | 43 |
| High confidence (70+) | 29 |
| Medium confidence (50-69) | 58 |

## Strategy Breakdown (87 classified)

| Strategy | Count |
|----------|-------|
| momentum_scalp | 50 |
| gap_and_go | 37 |

## Key Finding

The Schwab closed trades are predominantly **same-day trades** (hold_days=0).
The longer-hold positions (PFE 238d, V 277d, ADBE 442d) have entry_price=0
because they were cost-basis transfers/corporate actions — correctly classified
as "unclassifiable."

The 87 classified trades add significant momentum/scalp evidence to the
strategy proof base. Combined with 11 Alpaca paper trades, total classifiable
evidence is now 98 trades.

## All Classifications Are human_review_only=true

No classification changes strategy activation, learning, or live trading.
