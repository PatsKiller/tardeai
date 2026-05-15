# Trade AI v12 — Screener Reference

**Updated:** 2026-05-15
**Config:** `assets/screeners.yaml` v12.3
**Source:** Finviz Elite (v=152 custom view)

## Overview

12 active Finviz screeners feed the proposal pipeline. Each screener is purpose-built for specific strategy types and run windows.

## Screener Schedule

| Time (ET) | Screeners Run | Purpose |
|-----------|---------------|---------|
| 04:00 | prime_setups, watchlist_setups | Pre-market momentum scan |
| 07:00 | prime_setups, watchlist_setups | Pre-market update |
| 09:00 | prime + watchlist + oversold_quality + post_earnings_gappers | Open prep — momentum + recovery + earnings |
| 10:00 | prime + watchlist + quality_pullback + speculative_growth + dividend_value + sector_leadership | First hour — full diversity |
| 12:00 | pm_breakout_confirmation + pm_volume_continuation + quality_pullback | Midday — breakout confirmation, no more scalp |
| 14:00 | pm_breakout + pm_volume + speculative_growth + dividend_value | Afternoon — growth + income confirmation |
| 16:00 | pm_volume + quality_pullback + defensive_quality + oversold_quality | Close read — defensive + recovery |
| 17:30 | prime_setups, watchlist_setups | Post-close scan |

## Screener Details

### Tier 1 — Momentum / Scalp (AM)

#### prime_setups
- **Strategy:** momentum_scalp, gap_and_go
- **Criteria:** RVOL >5x, gap >10%, price $2-20, float <50M, cap small/under
- **Avg Volume:** 100K+
- **Run windows:** 0400, 0700, 0900, 1000, 1730
- **Quality gate at promoter:** $3+ price floor, 3% spread max, RSI <80

#### watchlist_setups
- **Strategy:** momentum_scalp, gap_and_go
- **Criteria:** RVOL >3x, gap >5%, price $1-30, float <100M, cap small/under
- **Avg Volume:** 100K+
- **Run windows:** 0400, 0700, 0900, 1000, 1730
- **Quality gate at promoter:** $3+ price floor, 3% spread max, RSI <80

### Tier 2 — Quality / Income / Dividend (AM + PM)

#### quality_pullback
- **Strategy:** swing_trade, fib_retracement_bounce, income_add
- **Criteria:** Mid+ cap, high dividend, payout <80%, avg vol 500K+, above SMA50 + SMA200, RSI 30-50
- **Run windows:** 1000, 1200, 1600
- **Purpose:** Quality names pulling back to support levels

#### dividend_value_pullback
- **Strategy:** dividend_growth_compounder, income_add, international_dividend
- **Criteria:** Dividend positive, payout <85%, 5y div growth >5%, RSI 30-50, avg vol 500K+
- **Run windows:** 1000, 1400
- **Purpose:** Dividend aristocrats on pullback

#### oversold_quality
- **Strategy:** recovery_watch, tax_loss_harvest
- **Criteria:** Mid+ cap, ROE positive, RSI oversold (<30), above SMA200, avg vol 500K+
- **Run windows:** 0900, 1600
- **Purpose:** Oversold quality names for recovery candidates

#### defensive_quality
- **Strategy:** reit_income, international_dividend, dividend_growth_compounder
- **Criteria:** High dividend, payout <85%, beta <1, sectors: REIT/utilities/consumer defensive, avg vol 500K+
- **Run windows:** 1600
- **Purpose:** Low-volatility income names

### Tier 3 — Event-Driven (AM)

#### post_earnings_gappers
- **Strategy:** earnings_post_momentum, swing_breakout
- **Criteria:** Earnings yesterday, avg vol 500K+, current vol 2000+, gap >5%
- **Run windows:** 0900
- **Purpose:** Post-earnings momentum plays

#### speculative_growth_breakouts
- **Strategy:** speculative_growth, swing_breakout
- **Criteria:** Small/mid+ cap, sales QoQ >20%, RVOL >2x, 4-week perf >20%, RSI 50-70
- **Run windows:** 1000, 1400
- **Purpose:** Revenue-growing small caps with momentum

#### sector_leadership_rs
- **Strategy:** sector_rotation
- **Criteria:** Fixed set of 11 sector ETFs (XLF, XLE, XLK, XLV, XLI, XLU, XLP, XLB, XLRE, XLC, XLY)
- **Run windows:** 1000
- **Purpose:** Sector relative strength ranking

### Tier 4 — PM-Specific (Afternoon Diversity)

#### pm_breakout_confirmation
- **Strategy:** swing_breakout
- **Criteria:** Mid+ cap, avg vol 500K+, RVOL >2x, new 20-day high, above SMA50
- **Run windows:** 1200, 1400
- **Purpose:** Confirms AM breakout setups that held into afternoon

#### pm_volume_continuation
- **Strategy:** swing_trade
- **Criteria:** Small+ cap, avg vol 500K+, price $5+, RVOL >1.5x, positive change
- **Run windows:** 1200, 1400, 1600
- **Purpose:** Sustained volume into afternoon — morning momentum holding

### Not Scheduled (Requires Position)

#### covered_call_candidates
- **Strategy:** covered_call_income
- **Criteria:** Mid+ cap, options available, avg vol 1000K+
- **Purpose:** IV rank screening for existing positions

## Data Retention

| Data Type | Retention | Location |
|-----------|-----------|----------|
| Raw Finviz CSV | 30 days | `data/raw/finviz/` |
| Merged scans | 30 days | `data/merged/` |
| trade_ai_scans (DB) | Indefinite | PostgreSQL |
| incubator_universe (DB) | Indefinite | PostgreSQL |

## Refresh Frequency

| Pipeline Stage | Frequency |
|----------------|-----------|
| Finviz screener hits | 8x/day (0400-1730 per schedule) |
| Technical enrichment | On ingestion |
| Strategy classification | Daily 6:35 AM |
| Strategy cards | Daily 6:50 AM |
| Incubator scoring | On ingestion |
| Proposal promotion | Hourly 7-17 M-F |

## Quality Gates (at promotion time)

| Gate | Threshold | Applies To |
|------|-----------|-----------|
| Price floor | $3+ momentum/scalp, $1+ others | All |
| Spread | <3% | All |
| RSI | <80 momentum, <75 swing, <85 all | All |
| Score | 42+ screener, 30+ classification | By source |
| Catalyst | Required for momentum (relaxed for income/dividend) | By strategy |

## Strategy Coverage Map

| Strategy | Screeners That Feed It |
|----------|----------------------|
| momentum_scalp | prime_setups, watchlist_setups |
| gap_and_go | prime_setups, watchlist_setups |
| swing_trade | quality_pullback, pm_volume_continuation |
| swing_breakout | pm_breakout_confirmation, post_earnings_gappers, speculative_growth_breakouts |
| earnings_post_momentum | post_earnings_gappers |
| speculative_growth | speculative_growth_breakouts |
| fib_retracement_bounce | quality_pullback |
| recovery_watch | oversold_quality |
| dividend_growth_compounder | dividend_value_pullback, defensive_quality |
| income_add | quality_pullback, dividend_value_pullback |
| reit_income | defensive_quality |
| international_dividend | dividend_value_pullback, defensive_quality |
| sector_rotation | sector_leadership_rs |
| covered_call_income | covered_call_candidates (requires position) |
| defense_thesis | (classification-based only, no screener) |
| core_growth_compounder | (classification-based only, no screener) |
| bond_income | (classification-based only, no screener) |
