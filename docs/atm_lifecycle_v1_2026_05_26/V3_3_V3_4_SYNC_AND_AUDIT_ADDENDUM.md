# v3.3/v3.4 Sync and Audit Addendum

**Date:** 2026-05-27  
**Commit:** `7f0a4f4`  

---

## 1. v3.3/v3.4 Implementation Summary

| Change | Detail |
|--------|--------|
| Schema | 3 new nullable columns: `order_submitted_at`, `order_filled_at`, `stop_verified_at` + 3 indexes. `stop_order_id` already existed. |
| API | `GET /api/v2/atm/stop-proof` + `GET /api/v2/atm/execution-timing-health` (both read-only) |
| UI | StopProofPanel + ExecutionTimingPanel added to ATM Control Room |
| Discovery | `unified_stop_supervisor.py` was already storing `stop_order_id` — no API/UI had exposed it before |

---

## 2. Current Stop Proof State

| Trade | Symbol | DB Stop | Stop Order ID | Status |
|-------|--------|---------|---------------|--------|
| #28 | NWG | $15.05 | `45b57b20-f947-4817-bf95-c2124c4c4cbe` | stop_unverified |
| #31 | AGNC | $9.71 | `f171e7ec-9224-4358-939e-1661feb5b64e` | stop_unverified |
| #33 | CMCSA | $23.61 | `e29b2971-1ff7-4024-8fd1-6c42fd89fe47` | stop_unverified |
| #34 | APPS | $6.93 | `accf1640-c6ba-4b9f-821b-acaf64db2f26` | stop_unverified |

All 4 open trades have Alpaca stop order IDs stored. "Unverified" means the read-only broker
verification pass has not yet been run against Alpaca's live order API.

---

## 3. APPS Orphan Repair (Audit Correction)

**This is a separate audit/trading-state repair, NOT part of the read-only v3.3/v3.4 visibility work.**

| Field | Detail |
|-------|--------|
| **Paper trade** | #34 (APPS) |
| **Action** | Reopened — paper_trades row linked to existing Alpaca position |
| **Alpaca order** | `bd2cf0ec...` — confirmed filled position in Alpaca Paper |
| **Stop change** | Replaced from $6.54 to $6.17 |
| **Reason** | DB had no matching paper_trade for an existing Alpaca open position (orphan). Repair linked the DB row to the broker position and set the correct stop level. |
| **Impact** | DB positions now match Alpaca broker state. Reconciliation health remains HEALTHY. |
| **Classification** | Trading-state repair / audit correction |

**This was NOT a new order.** It was a reconciliation of an existing broker position that had no matching DB row.

---

## 4. Cron / ATM Operating Repair (Commit `140d531`)

**Separate from v3.3/v3.4. Captured here for audit completeness.**

| Change | Detail |
|--------|--------|
| **PROJ/PY variables** | Moved to top of crontab for consistent resolution |
| **SHELL=/bin/bash** | Added to crontab header |
| **source syntax** | Changed to POSIX-compatible `. .env` |
| **Cron jobs functional** | 181 cron entries now running correctly |
| **ATM start_et** | Changed from 09:35 to 07:00 (wider premarket window) |
| **ATM cron schedule** | Widened from `9-15` to `7-15` |
| **Live price validation** | Added to `strategy_signal_sync.py` |

---

## 5. Safety Confirmation

| Control | Status |
|---------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| ATM mode | active (paper-mode constrained, manual_kill_switch_only) |
| Live orders | NONE |
| Stop modified | YES — APPS stop replaced $6.54 → $6.17 as audit repair (not v3.3/v3.4) |
| Proposals changed | NONE |

---

## 6. Rollback

**v3.3/v3.4 visibility rollback:**
```bash
git revert 7f0a4f4
ALTER TABLE paper_trades DROP COLUMN IF EXISTS order_submitted_at;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS order_filled_at;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS stop_verified_at;
```

**APPS repair is NOT rolled back by v3.3/v3.4 revert.** It was a separate trading-state correction.
