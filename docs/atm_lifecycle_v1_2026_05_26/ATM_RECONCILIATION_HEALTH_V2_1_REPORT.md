# ATM Reconciliation Health v2.1 Report

**Date:** 2026-05-27  

## Files Changed

| File | Change |
|------|--------|
| `scripts/api_v2.py` | Added `GET /api/v2/atm/reconciliation-health` |
| `apps/command-center-v2/src/components/ReconciliationHealthPanel.tsx` | NEW — reusable panel component |
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | Import + place panel above Position Source Reconciliation |
| `apps/command-center-v2/src/pages/SystemHealth.tsx` | Import + place compact panel above LLM Router |

## API Endpoint

`GET /api/v2/atm/reconciliation-health` returns:
- status: healthy
- db_open_count: 3
- journal_open_count: 3
- matched_count: 3
- mismatch_count: 0
- cron_fresh: true
- age_minutes: 21
- latest_items: 3 (all matched_open)
- unresolved_items: 0

## Build Result

`npm run build` — clean, 281ms

## Screenshots

- `atm_reconciliation_health_v2_1_atm_control_room.png`
- `atm_reconciliation_health_v2_1_system_health.png`

## Safety

- ALPACA_MODE=paper, LLM_DISABLE=true
- Read-only endpoint, no writes
- No orders placed, no positions modified

## Rollback

Restore backups from `docs/atm_lifecycle_v1_2026_05_26/backups/`
