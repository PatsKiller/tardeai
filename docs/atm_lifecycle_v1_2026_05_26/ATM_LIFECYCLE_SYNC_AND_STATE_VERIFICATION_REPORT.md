# ATM Lifecycle Sync and State Verification Report

**Date:** 2026-05-26  
**Commit:** `716e9bf`  

## Safety Confirmation

| Control | Status |
|---------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| ATM mode | not changed |
| Orders placed | NONE |
| Positions modified | NONE |
| Proposals expired during verification | NONE |

## Discrepancy Resolution

The operator reported the browser page still showed stale_proposals=78 and 1 missing decision.
This was caused by **browser cache showing pre-hygiene data**. The issue was NOT a code or server problem.

| Source | Stale Proposals | Missing Decisions | Status |
|--------|----------------|-------------------|--------|
| **Database** | 27 | 0 | CORRECT |
| **API** | 27 | 0 | CORRECT |
| **Fresh screenshot** | 27 | 0 | CORRECT |
| Operator's cached page | 78 | 1 | STALE CACHE (resolved by refresh) |

**No server restart was needed.** The API was already serving correct data.

## Database Validation

### Overdue Decisions

| Metric | Value |
|--------|-------|
| Total decision records | 12 |
| Unique trades with decisions | **10 of 10** |
| GCTS #20 | review_for_manual_close |
| GCTS #22 | missing_data_verify_first |
| GCTS #23 | review_for_manual_close |
| FLYW #19 | missing_data_verify_first (3 duplicate records) |
| Missing decisions | **0** |

### Stale Proposals

| Metric | Value |
|--------|-------|
| Current stale (>48h, no decision) | **27** |
| Expired by hygiene | **51** |
| Linked to open trades | 13 (correctly kept) |
| Recent 2-7 day (no open trade) | 14 (normal pipeline window) |

## API Validation

| Endpoint | Field | Value |
|----------|-------|-------|
| /api/v2/atm/lifecycle | stale_proposals | **27** |
| /api/v2/atm/lifecycle | open_positions | 29 |
| /api/v2/atm/lifecycle | time_stop_overdue | 10 |
| /api/v2/atm/lifecycle | stop_missing_count | 2 |
| /api/v2/atm/lifecycle | lifecycle_events_24h | 41 |
| /api/v2/atm/lifecycle | classifier_gate_disabled | true |
| /api/v2/atm/overdue-decisions | overdue_count | 10 |
| /api/v2/atm/overdue-decisions | recorded_decisions | **10** |
| /api/v2/atm/overdue-decisions | missing_decisions | **0** |

## UI Screenshot Validation

3 screenshots captured after hygiene:
- `atm_control_room_after_hygiene_sync.png` — shows Stale Proposals=27, 0 need decisions
- `automated_trade_mode_after_hygiene_sync.png` — classifier banner visible
- `system_health_after_hygiene_sync.png` — trust panel visible

All pages load without errors. No stale data visible.

## Drive Sync

Pending sync after this report.

## Remaining Risks

1. **10 overdue positions still open** — decisions recorded but no action taken yet
2. **2 positions missing DB stops** (GCTS #23, FLYW #19)
3. **Classifier gate OFF** (cold-start burn-in)
4. **FLYW #19 has 3 duplicate decision records** (harmless, API shows latest)
5. **14 recent proposals (4-6 days)** will age into stale if not acted on

## Next Recommended Action

The overdue position decisions are all recorded. The next phase options are:
1. **Execute the recorded decisions** — manually close the 5 positions marked review_for_manual_close
2. **Broker stop proof** — wire Alpaca API read-only check for the 2 missing stops
3. **Decision dedup** — add upsert logic to prevent duplicate decision records
