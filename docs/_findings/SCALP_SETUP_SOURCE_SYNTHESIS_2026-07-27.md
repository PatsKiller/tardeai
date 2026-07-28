# Scalp Setup — Source Synthesis (2026-07-27)

Three external articles were reviewed as **educational source material, not proof of edge**. No article
win-rate or target is presented as a Trade AI fact — Trade AI performance comes only from its own recorded
outcomes. Sources map to the three architectural layers, not to three competing engines.

## TradeZella — named setups (Layer A) · SOURCE-DERIVED
https://www.tradezella.com/blog/scalping-strategies

- **Level 2 Momentum Breakout** → `SCALP_L2_MOMENTUM_V1`. Catalyst gap, exceptional early volume,
  directional book stacking, short consolidation, break with bids lifting; **book flip = immediate
  invalidation**; primarily 09:30–11:00. Requires real Level-2 (T2). SOURCE-DERIVED mechanic;
  thresholds are CONFIGURABLE.
- **VWAP Scalp** → **split into two** (the article conflates them): `SCALP_VWAP_PULLBACK_V1`
  (continuation, trend-side pullback to VWAP on declining volume) and `SCALP_VWAP_REVERSION_V1`
  (mean reversion from a stretched price). They must never share a label. Regular variants do not fire
  before 09:45 (VWAP establishing in the opening 15 min — SOURCE-DERIVED).
- **15-Minute Opening Range Breakout** → `SCALP_ORB_15_BREAKOUT_V1`. Build 09:30–09:44, fire ~09:45–10:30
  on a close outside the range with volume + market alignment. SOURCE-DERIVED window and conditions.
- **Micro Pullback** → `SCALP_MICRO_PULLBACK_V1`. Strong leg → declining-volume retrace to VWAP/1m-MA →
  reversal-candle high. Overlaps the engine's existing impulse/pullback FSM → **reuses** it (does not
  create a second engine).

TradeZella also emphasizes tagging every trade by its actual setup and analyzing expectancy / time-of-day
separately — reflected in the additive event columns + journal filters.

## Kotak Neo — one-minute method → confirmation profile (Layer B) · SOURCE-DERIVED + ADAPTATION
https://www.kotakneo.com/investing-guide/trading/1-minute-scalping-strategy/

Not specific enough to be an independent setup. Implemented as the confirmation overlay layer:
actively-traded security, 1-minute chart, support/resistance, visible trend, increasing activity, multiple
aligned indicators (EMA/VWAP/RSI/MACD/volume), predefined target/stop. The article gives **no exact
periods or numeric thresholds** — those are CONFIGURABLE THRESHOLDs / TRADE AI ENGINE ADAPTATION, not
invented as sourced. Surfaced as `ONE_MIN_CONFLUENCE`, which **never authorizes a fire on its own in v1**.

## Bullish Bears — liquidity/spread → universal gate (Layer C) · SOURCE-DERIVED principle
https://bullishbears.com/scalping-stocks/

Contributes the execution-quality layer, not a chart pattern: tight bid-ask spread, sufficient
volume/liquidity, avoid/suspend scalping when spreads widen, measure expected vs actual execution, prefer
price-controlled orders over market orders (wider spreads → slippage). Implemented as the universal
`LIQUIDITY/SPREAD GATE` that can veto any setup; numeric limits are CONFIGURABLE THRESHOLDs.

## Explicitly NOT claimed (UNVALIDATED HYPOTHESIS)

- Any article win-rate/expectancy is **not** a Trade AI result.
- v1 IGN weights remain frozen v1 priors, labeled UNVALIDATED / PRIOR WEIGHTS; no refit on insufficient data.
- Edge is unproven — all setups run SHADOW / MANUAL_PAPER_TEST_ONLY until Trade AI's own recorded outcomes justify otherwise.
