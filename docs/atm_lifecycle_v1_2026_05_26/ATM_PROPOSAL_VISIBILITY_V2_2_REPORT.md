# ATM Proposal Visibility v2.2 Report

**Date:** 2026-05-27  

## Files Changed

| File | Change |
|------|--------|
| `scripts/api_v2.py` | Added `GET /api/v2/atm/proposal-hygiene` |
| `apps/command-center-v2/src/components/ProposalHygienePanel.tsx` | NEW — proposal visibility component |
| `apps/command-center-v2/src/pages/ATMControlRoom.tsx` | Replaced blank Recent Proposals with ProposalHygienePanel |

## API Endpoint

`GET /api/v2/atm/proposal-hygiene` returns:

| Field | Value |
|-------|-------|
| total_count | 114 |
| recent_count | 16 |
| stale_count | 15 |
| needs_review_count | 44 |
| linked_open_trade_count | 3 |
| duplicate_count | 29 |
| blocked_count | 0 |
| expired_count | 51 |

## Classification Breakdown

- **Recent pipeline window (16):** Within 7-day threshold, normal
- **Stale needs review (15):** Older than 7 days, not linked to open trade
- **Linked to open trade (3):** CMCSA, AGNC, NWG — correctly kept
- **Duplicate candidate (29):** Same symbol/strategy appears multiple times
- **Expired (51):** Already expired by prior hygiene run
- **Missing metadata (0):** All proposals have IDs and timestamps

## Build

`npm run build` — clean, 336ms

## Screenshot

`screenshots/atm_proposal_hygiene_v2_2_panel.png`

## Safety

- Read-only endpoint, no proposals modified
- ALPACA_MODE=paper, LLM_DISABLE=true
- No orders placed

## Rollback

Restore backups from `docs/atm_lifecycle_v1_2026_05_26/backups/`
