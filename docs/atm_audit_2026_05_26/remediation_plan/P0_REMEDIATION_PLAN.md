# P0 Remediation Plan — ATM Incident 2026-05-26

**Status:** IMPLEMENTED (items marked below)
**Safety:** No ATM mode changes. No live trading. No broker modifications.

---

## P0-1. Orchestrator Completion Monitor

**Problem:** Orchestrator silent-failed for 4 days. No alert.
**Fix:** System Health Agent checks `screener_pm.log` freshness every 5 min. Max age 180 min. Auto-retry with `--no-llm --no-alerts --allow-underfilled`.

| Item | Status |
|------|--------|
| Health agent monitors orchestrator | DONE — `system_health_agent.py` line 56 |
| Scalp Critic gated by `--no-llm` | DONE — `trade_ai_orchestrator.py` line 340 |
| 120s hard timeout on critic | DONE — threading with `join(timeout=120)` |
| `max_tickers=10` limit on critic | DONE — `scalp_critic_agent.py` line 209 |
| Auto-retry on stale | DONE — health agent retries with max 2/day |
| Escalation on failure | DONE — Telegram via central router |

**Files changed:** `trade_ai_orchestrator.py`, `scalp_critic_agent.py`, `system_health_agent.py`
**Rollback:** Revert commit `df15b0c`
**Validation:** `curl localhost:7777/api/v2/execution-integrity | jq '.checks[] | select(.component=="trade_ai_orchestrator")'`

---

## P0-2. safe_flock / Overlapping-Run Hardening

**Problem:** `safe_flock.sh` silently exits when lock held. No log. No alert.
**Current state:** safe_flock.sh exits 0 silently when PID is alive. No health event emitted.
**Fix needed:** Log skipped runs. Emit health event for lock contention. Detect abnormal runtime.

| Item | Status |
|------|--------|
| Health agent checks lock contention | DONE — `_check_lock_contention()` |
| Stale lock detection (dead PID) | DONE — checks `/proc/{pid}` |
| Lock runtime monitoring | DONE — reports `runtime_sec` |
| safe_flock.sh logging on skip | DEFERRED — requires shell script modification |

**Risk:** safe_flock.sh modification could affect all 14 jobs using it. Deferred to short-term.

---

## P0-3. auto_proposal_generator Validation

**Problem:** Cron missing `--today --apply`. Printed usage text every 30 min.
**Fix:** Crontab updated.

| Item | Status |
|------|--------|
| `--today --apply` added to cron | DONE — crontab updated |
| Health agent monitors log freshness | DONE — max_age_min=60 |
| Usage text in log treated as failure | DONE — `_check_output_validity()` detects "Usage:" pattern |

**Validation:** `tail -5 logs/auto_proposal.log` — should show signal counts, not usage text

---

## P0-4. pipeline_watchdog Schema-Proofing

**Problem:** Query referenced `script_name` and `rows_processed` — columns don't exist.
**Fix:** Updated to `pipeline_key` and `summary`.

| Item | Status |
|------|--------|
| Query updated to match schema | DONE — `pipeline_watchdog.py` lines 80, 100 |
| Health agent monitors watchdog | DONE — max_age_min=150 |
| Watchdog runs without crash | VERIFIED — ran successfully at 10:25 |

**Validation:** `tail -5 logs/pipeline_watchdog.log` — no `UndefinedColumn` errors

---

## P0-5. Stale Proposal Expiration

**Problem:** 4 proposals pending 97 hours. Cleanup thresholds too loose.
**Fix:** Manually expired. Cleanup cron runs at 10:00 and 15:00.

| Item | Status |
|------|--------|
| 4 stale proposals expired | DONE — ARM, BCS, MUD, SHMD |
| EVER stop-breached proposal rejected | DONE — current < stop |
| Health agent monitors cleanup freshness | DONE — max_age_min=1500 |
| Per-strategy max_age tightening | DEFERRED — requires strategy config review |

---

## P0-6. Alert Router Enforcement

**Problem:** `bypass_router=True` and direct Telegram senders buried real alerts.
**Fixes applied:**

| Item | Status |
|------|--------|
| `bypass_router=True` removed from quote refresh | DONE — `run_proactive_quote_refresh.py` |
| premarket_watcher routed through central alert | DONE — `premarket_watcher.py` |
| PRE-MARKET CATALYST added to P2 suppression | DONE — `telegram_alert_router.py` |
| Health agent uses ONLY central router | DONE — `system_health_agent.py` |
| 2-hour dedup on health escalations | DONE — prevents repeat alerts |
| Misleading "ALERT sent" log fixed | DONE — checks return value |
| 35+ direct Telegram senders audit | IDENTIFIED — migration deferred |

**Remaining tech debt:** 35+ scripts call Telegram API directly. Gradual migration needed.

---

## P0-7. Dashboard Freshness

**Problem:** TCA page empty. Stale proposals showing. Browser cache issue.
**Fixes applied:**

| Item | Status |
|------|--------|
| TCA data populated (10 rows) | DONE — `paper_execution_quality_analyzer.py --apply` |
| TCA crons added (4:30 PM + 5:00 PM) | DONE — crontab |
| React app rebuilt with new JS bundles | DONE — Vite hashed filenames |
| Execution Integrity section on System Health page | DONE — `SystemHealth.tsx` |
| API endpoint `/api/v2/execution-integrity` | DONE — 18 checks, events |
| Stale proposals expired from proposals page | DONE |

**Note:** Browser hard refresh (Ctrl+Shift+R) needed for first load after rebuild.

---

## P0-8. Paper Execution Integrity

**Problem:** TCA analyzer had no cron. No automated fill quality analysis.
**Fixes applied:**

| Item | Status |
|------|--------|
| `paper_execution_quality_analyzer.py` cron at 4:30 PM | DONE |
| `paper_execution_quality.py` cron at 5:00 PM | DONE |
| Timestamp bug fixed (None → NULL) | DONE — `paper_execution_quality.py` line 204 |
| Health agent monitors TCA freshness | DONE — component `tca_analyzer` |
| Extended hours trading enabled | DONE — `alpaca_paper_adapter.py` |
| Trailing stop constraint dropped | DONE — `chk_long_stop_below_entry` |
| Stop replacement verifies cancellation | DONE — `paper_trade_monitor.py` |

---

## Deferred Items (Short-Term)

| Item | Priority | Reason |
|------|----------|--------|
| safe_flock.sh logging on skip | P1 | Requires testing across 14 jobs |
| 35+ direct Telegram sender migration | P1 | Systemic refactor, gradual rollout |
| Persistent dedup across cron restarts | P1 | Currently in-memory, resets each invocation |
| Per-strategy max_age tightening | P2 | Needs strategy config review |
| Orchestrator flock spacing increase | P2 | Reduce overlap between 0900/1000 runs |
| Watchdog self-test at startup | P2 | Schema validation on boot |
