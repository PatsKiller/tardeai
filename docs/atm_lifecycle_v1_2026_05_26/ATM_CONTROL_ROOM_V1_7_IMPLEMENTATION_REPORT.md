# ATM Control Room v1.7 Implementation Report

**Date:** 2026-05-26  
**Source:** ChatGPT-designed replacement from Google Drive  
**Source URL:** https://docs.google.com/document/d/1liWZuU6ecM6Lu3wGDoimb-xFrRVuQzk1QcidLtJ7Hx0  
**Backup:** `backups/ATMControlRoom.tsx.pre_v1_7_*`  

## Files Changed

| File | Change |
|------|--------|
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | Full replacement with ChatGPT v1.7 design |

## Fix Applied

The downloaded component used `getJson()` which returned the raw API envelope `{ok, data}`. Added `v?.data || v` unwrapping for all 4 API calls (lifecycle, overdue, manualClose, reconciliation) and close preview.

## Build Result

`npm run build` — clean, 259ms

## Validation

| Check | Result |
|-------|--------|
| Trust strip shows live data | YES — 14/2/13/2/0/27/0/0/OFF/46 |
| Open Positions shows 13 records | YES |
| Gate chips readable | YES — Strategy, Classifier, Max Conc., Stop, Premarket with status |
| Close Reconciliation shows INFU #9 | YES — with View + Close Preview buttons |
| Overdue queue shows reviewed | YES — 2 positions, all reviewed |
| Manual close shows reviewed | YES — 1 position, reviewed |
| Recent Proposals shows 20 records | YES |
| Control Gaps shows accurate counts | YES |
| Inspector has tabs | YES — Overview, Records, Lifecycle, Risk/Gates, Actions, Raw |
| No orders placed | CONFIRMED |
| Safety unchanged | CONFIRMED |

## Screenshots

- `atm_control_room_v1_7_main.png` — full page with all sections populated

## Safety

- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- ATM mode unchanged
- No orders placed

## Rollback

```bash
cp docs/atm_lifecycle_v1_2026_05_26/backups/ATMControlRoom.tsx.pre_v1_7_* apps/command-center-v2/src/pages/ATMControlRoom.tsx
cd apps/command-center-v2 && npm run build
```
