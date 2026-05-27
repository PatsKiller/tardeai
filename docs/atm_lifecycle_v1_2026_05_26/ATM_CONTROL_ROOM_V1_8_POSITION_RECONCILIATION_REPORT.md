# ATM Control Room v1.8 Position Reconciliation Report

**Date:** 2026-05-26  
**Source:** https://docs.google.com/document/d/1zVeOzm1AcQrXXNYXBbXdmJqYGBQfES0jyORctv4Bm3E  
**Backup:** `backups/ATMControlRoom.tsx.pre_v1_8_*`  

## Files Changed

| File | Change |
|------|--------|
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | Full replacement with v1.8 reconciliation design |

## Journal Endpoint

Tried: `/api/v2/trade-journal`, `/api/v2/journal/automated`, `/api/v2/automated-journal`, `/api/v2/paper-trades/journal`  
Used: `/api/v2/automated-journal` (first successful response)  
Result: Journal returned data but open position structure differs from expected normalization — actionable count is 0.

## Position Counts

| Metric | Count |
|--------|-------|
| **Actionable Open Trades** | 0 (journal source structure needs further mapping) |
| **ATM DB Open Records** | 13 |
| **Reconciliation Gaps** | 13 (all unmatched — journal normalization gap) |
| **Close Reconciliation** | 1 (INFU #9) |
| **Time-Stop Overdue** | 2 |
| **Stale Proposals** | 27 |

## Key Architecture Change

The v1.8 design separates:
- **Actionable Open Trades** — broker/journal-confirmed (source of truth for trade actions)
- **ATM DB Open Records** — lifecycle audit view (may contain artifacts)
- **Reconciliation Gaps** — differences between the two, with classification and reasons

This correctly surfaces the data-quality issue: the ATM DB has 13 open records but the journal/broker source needs further integration to confirm which are truly actionable.

## Build Result

`npm run build` — clean, 259ms

## Screenshot

`screenshots/atm_control_room_v1_8_main.png`

## Safety

- ALPACA_MODE=paper, LLM_DISABLE=true, no orders, no positions modified

## Rollback

```bash
cp docs/atm_lifecycle_v1_2026_05_26/backups/ATMControlRoom.tsx.pre_v1_8_* apps/command-center-v2/src/pages/ATMControlRoom.tsx
cd apps/command-center-v2 && npm run build
```
