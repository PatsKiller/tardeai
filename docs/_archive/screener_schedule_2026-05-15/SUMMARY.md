# Screener Schedule Optimization — 2026-05-15

## Trigger
Live audit found 1 dead screener and 8 strategies stuck at 1 scan/day.

## NOT TOUCHED (operator directive)
- prime_setups (feeds momentum_scalp + gap_and_go) — UNCHANGED
- watchlist_setups (feeds momentum_scalp + gap_and_go) — UNCHANGED
- Their windows still include 'test-fix' and '1730' — deferred

## Changes Applied (9 screeners modified, NONE feed momentum_scalp)
| Screener | Before | After |
|----------|--------|-------|
| covered_call_candidates | [] (dead) | [1000, 1400] |
| defense_aerospace | [1000] | [1000, 1400] |
| core_growth_compounders | [1000] | [1000, 1400] |
| post_earnings_gappers | [0900] | [0900, 1400] |
| sector_leadership_rs | [1000] | [1000, 1400] |
| bond_income_defensive | [1200] | [0900, 1200] |
| high_yield_bdc_income | [1200] | [0900, 1200] |
| defensive_quality | [1600] | [1200, 1600] |
| core_index_etfs | [1600] | [1200, 1600] |

## Verification
- No-touch verified: prime_setups + watchlist_setups byte-identical
- 8 strategies moved from 1 scan/day to 2 scans/day
- momentum_scalp pipeline cadence unchanged
- 83/83 Phase 6 tests pass
