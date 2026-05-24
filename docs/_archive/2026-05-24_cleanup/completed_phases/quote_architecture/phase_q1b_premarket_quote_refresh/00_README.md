# Q-1B — Premarket Quote Refresh Cadence

**Status:** COMPLETE

## What Changed

Q-1 previously started at 09:00 ET. Q-1B adds 6 premarket entries starting at 06:00 ET:

| Time ET | Mode | Targets | Purpose |
|---------|------|---------|---------|
| 06:00 | pending | Active proposals | First premarket refresh |
| 06:30 | incubator | High-priority candidates | Incubator movement check |
| 07:00 | pending | Active proposals | Due diligence input |
| 07:30 | pending | Active proposals | Quote/liquidity refresh |
| 08:00 | pending | Active proposals | Morning packet input |
| 08:30 | pending | Active proposals | Pre-open movement/spread |

Existing Q-1 entries (09:00-15:00 every 5min) remain unchanged.

## Why

- CODX has RVOL 301x and +42% gap — needs monitoring before open
- INGM needs quote context before operator reviews at 08:00
- Waiting until 09:00 leaves too much uncertainty too close to open

## Safety

- Premarket refresh is research/context only
- Does not make proposals execution-ready
- Execution-ready requires market-session quote + all hard gates
- No trades, no orders, no approvals
- Rollback: `rollback_q1b_premarket_quote_refresh.sh`

## Tests

7/7 pass.
