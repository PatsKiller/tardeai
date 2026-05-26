# P0.5B Control Hardening Report

**Date:** 2026-05-26  
**Git Baseline:** `808e47cff376e63a7f6c7ee2d53680631cdc5894` (P0.5A)  
**Backup:** `docs/atm_audit_2026_05_26/designer_review/backups/p05b_pre_apply_backup_20260526_1513.tgz`  

---

## Files Changed

| File | Change |
|------|--------|
| `scripts/system_health_agent.py` | Added safe_flock JSONL event ingestion + analysis |
| `scripts/api_v2.py` | Added classifier_guardrail to ATM status, safe_flock/time_stop/alert_routing to execution-integrity |
| `scripts/audit_direct_telegram_senders.py` | NEW: Direct Telegram sender audit script |
| `apps/command-center-v2/src/pages/AutomatedTradeMode.tsx` | Added classifier gate disabled banner |
| `apps/command-center-v2/src/pages/SystemHealth.tsx` | Added Control Plane Trust panel |
| `reports/direct_telegram_sender_audit.json` | NEW: Audit results |
| `docs/.../alert_routing_direct_sender_audit.md` | NEW: Audit markdown report |
| `docs/.../P05B_CONTROL_HARDENING_REPORT.md` | This report |

---

## Safety Confirmations

| Control | Before | After |
|---------|--------|-------|
| ALPACA_MODE | paper | paper |
| LLM_DISABLE_LIVE_EXECUTION | true | true |
| manual_kill_switch_only | true | true |
| min_classifier_health | 0.0 | 0.0 (unchanged, visibility only added) |
| Orders placed | none | none |
| ATM mode | not changed | not changed |
| Positions opened/closed | none | none |
| Stop prices modified | none | none |
| Crons modified | none | none |
| .env modified | no | no |

---

## Phase Results

### Phase 1: System Health Agent safe_flock Ingestion

- Reads `logs/safe_flock_events.jsonl` (30-min lookback window)
- Tracks: lock_skip, stale_lock_cleared, command_failed, repeated_lock_skip
- Writes system_health_events rows for anomalies
- Repeated lock skip: 2+ in 30min = CRITICAL for critical components, WARN otherwise
- Dry-run output: `safe_flock: 12 events, 0 skips, 0 repeated, 0 stale cleared, 0 cmd failures`
- Apply run: succeeded, no new DB events (clean state)

### Phase 2: Classifier Health Guardrail Visibility

- `/api/v2/atm/status` now includes `classifier_guardrail` block
- Fields: `classifier_health_min`, `classifier_gate_disabled`, `classifier_gate_reason`, `classifier_graduation_blocked`, `production_threshold`
- Direct test: `classifier_gate_disabled: True`, `classifier_gate_reason: cold_start_burn_in`
- Dashboard: amber banner "Classifier Gate Disabled — Cold-start burn-in active"

### Phase 3: Time-Stop Review-Only Surfacing

- `/api/v2/execution-integrity` now includes `time_stop_summary`
- Fields: `total_open`, `overdue_count`, `review_due_count`, `approaching_count`, `overdue_positions`
- Direct test: 29 open, 10 overdue (all intraday strategies held overnight)
- Overdue: MNKD(19d), SMX(19d), INFU(15d), BLBD(14d), EVC(15d), GCTS(13d), FLYW(14d)
- Dashboard: time-stop overdue metric + overdue position list
- **No positions were closed. No stops were moved. Review-only.**

### Phase 4: Direct Telegram Sender Audit

- Script: `scripts/audit_direct_telegram_senders.py`
- Results: 81 files with Telegram refs, 10 central, 4 bypass risk, 34 direct API, 35 migration candidates
- Reports: `reports/direct_telegram_sender_audit.json` + `docs/.../alert_routing_direct_sender_audit.md`
- Optional `--fail-on-new` flag available but not enabled in cron

### Phase 5: Dashboard Trust Panel

- Added to SystemHealth.tsx: "Control Plane Trust" card
- Metrics: safe_flock skips, repeated skips, stale locks, time-stop overdue, Telegram bypass count
- Overdue positions listed with symbol, strategy, hold days, type

---

## API Validation

| Endpoint | Field | Value | Status |
|----------|-------|-------|--------|
| `/api/v2/atm/status` | `classifier_guardrail.classifier_gate_disabled` | `true` | PASS |
| `/api/v2/atm/status` | `classifier_guardrail.classifier_gate_reason` | `cold_start_burn_in` | PASS |
| `/api/v2/execution-integrity` | `safe_flock.events_seen` | `18` | PASS |
| `/api/v2/execution-integrity` | `time_stop_summary.overdue_count` | `10` | PASS |
| `/api/v2/execution-integrity` | `alert_routing.migration_status` | `P0.5_AUDIT_ONLY` | PASS |

Note: Running server has old module cached. API results confirmed via direct Python import test.
Server restart will pick up changes.

## Frontend Build

```
npm run build: ✓ built in 251ms (zero errors)
```

---

## Known Remaining Risks

1. **Server restart needed** — running portfolio_server.py has old api_v2 module cached. Next restart picks up all changes.
2. **10 overdue intraday positions** — GCTS, MNKD, SMX, BLBD, EVC, INFU, FLYW are momentum/gap positions held well past intraday close. Operator review required.
3. **34 direct API Telegram senders** — migration to central `send_telegram()` is a future P1 task.
4. **4 bypass_router files** — `system_health_agent.py`, `send_closed_trade_digest.py`, `telegram_alert.py`, `cron_wrapper.sh` need review.

---

## Rollback Commands

```bash
# Restore from backup
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
tar xzf docs/atm_audit_2026_05_26/designer_review/backups/p05b_pre_apply_backup_20260526_1513.tgz

# Or git revert
git revert HEAD
```
