# P0 Proposal Lifecycle Fix Report — 2026-05-29

## P0 #1 — expired/EXPIRED case inconsistency: FIXED
- **File**: `scripts/api_v2.py`
- **Function**: `_expire_stale_proposals(conn)`
- **Lines changed**: 7501, 7510, 7519
- **Change**: `SET status='expired'` → `SET status='EXPIRED'` (3 UPDATE statements)
- **Impact**: Future expirations will use uppercase. Prevents recurrence.
- **DB mutations**: NO — existing 3 lowercase rows are normalized at query time

## P0 #2 — hygiene panel status field: FIXED
- **File**: `scripts/api_v2.py`
- **Endpoint**: `GET /api/v2/atm/proposal-hygiene`
- **Lines changed**: 20462-20467 (added `status` to SELECT), 20494-20500 (classification logic), 20508-20513 (response format)
- **Change**: Classification now uses `status` (normalized uppercase) instead of `signal_decision`
- **Response**: Added `signal_decision` as separate field; `status` now shows normalized lifecycle status
- **DB mutations**: NO

## Files Changed
- `scripts/api_v2.py` — 5 edits (3 for bug #1, 3 for bug #2, one shared query change)

## Endpoints/Functions Changed
| Function/Endpoint | Change |
|-------------------|--------|
| `_expire_stale_proposals()` | `status='expired'` → `status='EXPIRED'` |
| `GET /api/v2/atm/proposal-hygiene` | SELECT adds `status`; classification uses `status` not `signal_decision` |

## Validation Results
| Check | Result |
|-------|--------|
| Python compile | PASS |
| API response | PASS — 65 expired (was ~62), 74 rejected, 2 linked, 0 stale |
| BLBD id=10 | FIXED — now classified as expired (was stale due to signal_decision=GO) |
| TLSI id=97 | FIXED — now classified as expired (was stale due to signal_decision=GO) |
| EVER id=124 | FIXED — now classified as expired |
| DB rows mutated | **NO** |
| Proposal mutations | **NO** |
| Frontend changes | **NO** |

## Remaining P0 Gaps
**NONE** — both P0 bugs are fixed.

## Remaining P1 Gaps
1. Add run_type column to backtesting Trades table
2. Surface 3,592/3,593 classification ratio in UI
3. SHFS id=860 dry-run + operator approval
4. Reconcile 13 orphan proposal/trade links
5. Fix ATM expiry to also update primary status (not just atm_expired_at)
6. Add proposal lifecycle inspector

## Rollback Plan
```bash
git revert <commit-hash>
```
No SQL rollback needed — no DB rows were changed.
