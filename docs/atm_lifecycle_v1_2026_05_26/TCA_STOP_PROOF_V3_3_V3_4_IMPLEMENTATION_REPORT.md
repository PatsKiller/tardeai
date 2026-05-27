# v3.3/v3.4 TCA Timing + Broker Stop Proof Implementation Report

**Date:** 2026-05-27  

## Schema Columns Added

- `paper_trades.order_submitted_at` TIMESTAMPTZ nullable
- `paper_trades.order_filled_at` TIMESTAMPTZ nullable
- `paper_trades.stop_order_id` TEXT nullable (already existed)
- `paper_trades.stop_verified_at` TIMESTAMPTZ nullable
- 3 new indexes

## API Endpoints Added

| Endpoint | Result |
|----------|--------|
| `GET /api/v2/atm/stop-proof` | 4 open, 0 verified, 0 missing OID, all stop_unverified |
| `GET /api/v2/atm/execution-timing-health` | 30 trades, 0 submitted, 0 filled (historical) |

## Key Finding

All 4 open trades already have `stop_order_id` stored from the existing unified_stop_supervisor! This was not visible before because no API exposed it. The stop proof panel now surfaces this data.

| Trade | Symbol | Stop | Order ID | Status |
|-------|--------|------|----------|--------|
| NWG | $15.05 | 45b57b20... | stop_unverified |
| AGNC | $9.71 | f171e7ec... | stop_unverified |
| CMCSA | $23.61 | e29b2971... | stop_unverified |
| APPS | $6.93 | accf1640... | stop_unverified |

## UI Panels Added

- StopProofPanel — shows DB stop, order ID, verification status per trade
- ExecutionTimingPanel — shows timing field population, missing fields

## Safety

- **Orders placed:** NONE
- **Stops modified:** NONE
- **Proposals changed:** NONE
- ALPACA_MODE=paper, LLM_DISABLE=true
- Build: clean (351ms)

## Rollback

```sql
ALTER TABLE paper_trades DROP COLUMN IF EXISTS order_submitted_at;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS order_filled_at;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS stop_verified_at;
```
