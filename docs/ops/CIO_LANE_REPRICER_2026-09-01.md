Status:      ACTIVE  
as_of:       2026-09-01T16:50:00-04:00  
Measured at: origin/main tip at branch open (contains #833 / `2fde58aa3`)  
Canonical repo path: docs/ops/CIO_LANE_REPRICER_2026-09-01.md  
Authority:   ops record for declaring the portfolio_repricer lane  
See also:    docs/ops/litmus/LITMUS_LANES_2026-09-01.md (F7 / F8)  
             config/lane_registry.json · scripts/check_lane_registry.py

# Declare portfolio_repricer lane (writes data_as_of)

## Verdict

**Promote: NO** unless the operator says `promote lanes`.  
Wake persist / cash_letter / #832 / #833 trees not edited. `$PROJ` not fast-forwarded.

## Problem (LITMUS_LANES F7)

`portfolio_repricer.py` writes `holdings.json` and `data_as_of`. Three installed
cron lines. No lane row. Five baseline entries (three of them the repricer
itself) kept it permanently exempt, so `check_lane_registry.py` could report
"clean" while the money writer was invisible.

## Change

| piece | what |
|---|---|
| `config/lane_registry.json` | ONE ACTIVE row `portfolio-repricer` |
| cadence | `expected_cadence_hours: 0.25` = installed `*/15 9-16` (not a fake 24h) |
| match | `portfolio_repricer.py` (covers */15, 5 9 open, 10 16 postclose) |
| artifact | `data/portfolios/state/holdings.json` — what CURRENT serves |
| baseline | remove the three portfolio_repricer cron lines (532 left; not a 535-row sweep) |
| note | F3 live_monitor and F5 warm_caches stay loose — out of scope |

## Explicit non-goals

- Do not wire `evaluate_lane` into cio-hardening  
- Do not add a new crontab  
- Do not "fix" price-cache `$PROJ` vs CURRENT (report only)  
- Do not tighten `portfolio_live_monitor` 24h → 0.33h  
- Do not declare 535 exempt crons  
- No wake persist, no cash_letter, no S5 hygiene  

## Acceptance

- Drop the new row while the cron is still discovered and no longer baselined → gate red  
- `check_lane_registry.py` → 0 undeclared NEW for portfolio_repricer  
)
