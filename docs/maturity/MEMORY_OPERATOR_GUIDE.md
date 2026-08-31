# Command Center — Durable Memory operator guide

Status:      ACTIVE
as_of:       2026-08-17T23:11:04-04:00
Measured at: efcc51365 / not measured

READ_ONLY_ADVISORY. Memory is durable. Memory is advisory. Memory is **not**
financial truth. Memory is **not** execution authority.

## Where to look

- Agents hub → **Memory** tab (`/v3/agents`)
- Health hub → Intelligence loop (same `MemoryPanel`)
- GET `/api/v3/maturity/memory`

The page shows backend health, status counts (CANDIDATE / ADMITTED / DISPUTED /
SUPERSEDED / EXPIRED / RETRACTED), contradictions, recent retrievals, and
SHADOW comparator counts.

## Authority

- `MEMORY_BEHAVIOR_INFLUENCE` must remain `0`.
- `GOVERNED_MEMORY_ADVISORY_INFLUENCE=SHADOW` records retrievals only.
- Program 2 lesson/FS SHADOW flags are independent and must stay as signed.
- Dashboard GET never places, cancels, or replaces orders.

## Operator actions

Dispute / retract / expire POST to `/api/v3/maturity-control/memory/{action}`
and require `MATURITY_CONTROL_ENABLED=1`. If control is disabled the buttons
return `control_disabled`. That is correct.

## Rollback

1. Set `MEMORY_PROVIDER=null` in the portfolio-server drop-in.
2. Keep `MEMORY_BEHAVIOR_INFLUENCE=0`.
3. Do not delete `data/cio/aif_memory.jsonl` (forensic evidence).
4. Restart only portfolio-server.

## Never

- Treat a memory as current price, cash, holdings, stops, risk, 2FA, or broker state.
- Enable memory as a path to broker/order/stop/risk/2FA authority.
- Start Program 4 (autonomous watchdog) from this surface.
