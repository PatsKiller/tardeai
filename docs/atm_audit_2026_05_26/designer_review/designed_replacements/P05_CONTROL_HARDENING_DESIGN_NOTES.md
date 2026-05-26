# P0.5 Control Hardening — Design Notes

**Author:** Claude Code (Chief Architect role)  
**Date:** 2026-05-26  
**Git Baseline:** `c1286d314deb377df49713e1646f139db7f43643`  
**Backup:** `backups/p05_pre_apply_backup_20260526_1500.tgz`  

## Scope

Five known control gaps identified in the post-fix ATM audit. This P0.5 package
addresses each with the minimum viable hardening that improves observability without
changing trading logic, ATM mode, or order flow.

## Design Decisions

### 1. safe_flock.sh — Observable Lock Guard

**Gap:** Silent `exit 0` on lock contention. No trace in any log.  
**Fix:** Full replacement with structured JSONL event logging.  
**Risk:** Zero. Only changes logging behavior. Same lock semantics.  
**Status:** APPLY NOW (Phase 2)

### 2. Drive Sync gog PATH — Cron Environment Fix

**Gap:** `gog` binary not found in cron PATH.  
**Fix:** Absolute path `/home/johnclaw/.local/bin/gog` in `sync-docs-to-drive.py`.  
**Risk:** Zero. Just resolves a path.  
**Status:** ALREADY APPLIED (earlier in session)

### 3. Classifier Health Guardrail — Visibility

**Gap:** `min_classifier_health: 0.0` silently bypasses the gate with no operator reminder.  
**Fix:** Add `classifier_guardrail` block to API + dashboard banner.  
**Risk:** Zero. Purely additive read-only data. No approval logic changes.  
**Status:** DESIGN COMPLETE — apply in future session

### 4. Time Stop Review Surfacing — Visibility

**Gap:** Time stop policy defined but never surfaced. Operator cannot see which
positions are overdue.  
**Fix:** Add `time_stop_status` per position in API + dashboard column.  
**Risk:** Zero. Read-only. No auto-close. No stop price changes.  
**Status:** DESIGN COMPLETE — apply in future session

### 5. Alert Routing Audit — Observability

**Gap:** 64 direct Telegram senders, 40 direct API callers, 3 bypass_router files.
No central audit trail.  
**Fix:** Add JSONL audit log to `telegram_alert.py:send_telegram()`. Expose inventory
in API. Future P1 migrates all direct callers.  
**Risk:** Zero. Append-only audit log. No send behavior changes.  
**Status:** DESIGN COMPLETE — apply in future session

## What Gets Applied NOW vs LATER

| Item | Apply Now | Apply Later |
|------|-----------|-------------|
| safe_flock.sh replacement | YES (Phase 2) | - |
| gog PATH fix | DONE | - |
| Classifier guardrail visibility | - | Next session (API + TSX changes) |
| Time stop surfacing | - | Next session (API + TSX changes) |
| Alert routing audit log | - | Next session (Python + API + TSX) |

## Safety Invariants Maintained

- ALPACA_MODE = paper (not changed)
- LLM_DISABLE_LIVE_EXECUTION = true (not changed)
- manual_kill_switch_only = true (not changed)
- min_classifier_health = 0.0 (not changed — only visibility added)
- No orders placed
- No positions opened or closed
- No stop prices modified
- No cron schedule changes
- No .env modifications
- No secrets exposed

## Architecture Notes

The system uses a single monolithic API file (`scripts/api_v2.py`, 1MB) serving all
`/api/v2/*` endpoints. Future hardening patches that add API fields need to be carefully
scoped to avoid regressions in the 1MB file. Consider extracting ATM-specific endpoints
into a separate module in a future refactor.

The Telegram alert stack has three layers:
1. `telegram_alert.py:send_telegram()` — entry point with optional bypass
2. `telegram_alert_router.py:should_send_telegram()` — rate limit/dedup
3. `telegram_alert_routing_policy.py` — severity classification

Most callers use layer 1. Some bypass all layers and call `requests.post` to
`api.telegram.org` directly. The P1 migration plan consolidates all senders through
layer 1 with mandatory caller attribution.
