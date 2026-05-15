# Screener Filter Population — 2026-05-15

## Trigger
7 of 18 screeners had empty Finviz filter strings (url_len=0). Plus covered_call_candidates had only 3 filters.

## NOT TOUCHED
- prime_setups, watchlist_setups (momentum_scalp) — byte-identical
- 8 working screeners (4-7 filters each) — byte-identical

## Changes Applied

| Screener | Strategy | Before | After | Filters |
|----------|----------|--------|-------|---------|
| earnings_catalyst_pre | earnings_catalyst | 0 | 5 | earnings within 5d, mid-cap, RSI 40-70, vol 500K+, price $10+ |
| core_growth_compounders | core_growth_compounder | 0 | 6 | large-cap, 5y EPS >15%, ROE >15%, margin >40%, above SMA200, vol 1M+ |
| bond_income_defensive | bond_income | 0 | 4 | ETF, yield >3%, beta <0.5, vol 500K+ |
| high_yield_bdc_income | high_yield_income_bdc | 0 | 4 | yield >5%, mid+ cap, vol 500K+, payout <110% |
| core_index_etfs | core_index | 0 | 3 | ETF, vol >5M, price >$50 |
| defense_aerospace | defense_thesis | 0 | 4 | aerospace/defense industry, mid+ cap, vol 500K+, above SMA200 |
| sector_leadership_rs | sector_rotation | 0 | 3 | ETF, 4-week perf >10%, vol 1M+ |
| covered_call_candidates | covered_call_income | 3 | 6 | +yield >2%, +beta 0.5-1.5, +price >$20 |

## Final State
- 18 screeners total, 0 empty, 2 marginal (3 filters), 16 good (4+ filters)
- All 20 strategies have screeners with real filters
