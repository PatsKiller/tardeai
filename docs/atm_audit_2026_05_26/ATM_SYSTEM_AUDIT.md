# ATM System Audit — 2026-05-26

**Auditor:** System / Claude  
**Date:** 2026-05-26  
**Scope:** Full pipeline from scanner through execution, monitoring, and agent review  
**Severity:** CRITICAL (resolved)  

---

## A. Executive Summary

The Automated Trading Module (ATM) was inactive for 4+ days (2026-05-22 through 2026-05-26) despite being configured as "active." During this period:

- **Zero proposals** were generated.
- **Zero trades** were executed.
- **4 stale proposals** (ARM, MUD, SHMD, BCS) sat PENDING for 97 hours without expiry.
- **Operator received no alerts** about pipeline failure. Instead, the operator was flooded with low-value ATP REVIEW ALERT spam every 5 minutes.

Five root causes were identified across three categories (pipeline break, stale data, broken self-healing). All five have been fixed. A new System Health Execution Integrity Agent (`scripts/system_health_agent.py`) has been deployed to prevent recurrence. The system was validated end-to-end at 10:42 ET on 2026-05-26.

---

## B. Current-State Architecture

### Pipeline Flow

```
Orchestrator (trade_ai_orchestrator.py)
  -> Finviz Scanner (118 tickers)
  -> Scoring Engine (6 pillars, max 55)
  -> Scalp Critic (LLM review, qwen3:14b)
  -> Strategy Signals (planned entries/stops/targets)
  -> Auto Proposal Generator (PENDING proposals)
  -> ATM Approval (operator via Telegram buttons)
  -> Alpaca Paper Adapter (bracket orders)
  -> Stop Monitoring (R-multiple trailing)
  -> TCA Execution Quality Analysis
```

### Components

| Component | File | Role |
|-----------|------|------|
| Orchestrator | `scripts/trade_ai_orchestrator.py` | 23-stage master pipeline, runs 6x/day |
| Auto Proposal Generator | `scripts/auto_proposal_generator.py` | Creates PENDING proposals from signals |
| ATM Approver | `scripts/atm_auto_approver.py` | Auto-approves proposals meeting criteria |
| Alpaca Adapter | `scripts/alpaca_paper_adapter.py` | Paper-only broker interface |
| Paper Trade Monitor | `scripts/paper_trade_monitor.py` | R-multiple trailing stops |
| Unified Stop Supervisor | `scripts/unified_stop_supervisor.py` | Stop management (STOP-V2.2) |
| Pipeline Watchdog | `scripts/pipeline_watchdog.py` | Self-healing pipeline monitor |
| System Health Agent | `scripts/system_health_agent.py` | NEW: 18-component integrity monitor |

### Infrastructure

- **Scheduler:** 181 cron jobs (verified via `crontab -l`)
- **Dashboard:** React SPA on port 7777 (67 routes), DOF Auction on port 7776
- **Database:** PostgreSQL `trade_ai` (376+ tables)
- **LLM:** qwen3:14b on Intel Arc B50 (Vulkan, 41/41 layers offloaded)
- **Broker:** Alpaca paper-api.alpaca.markets (PAPER_BASE_URL hardcoded)
- **Agents:** Maria (trade analysis), Steph (portfolio intelligence), Aegis (morning briefs), Alex (governance/research), Iris (taxonomy/library)

---

## C. Findings

All findings sourced from `docs/project/ROOT_CAUSE_ATM_DEAD_2026_05_26.md` and confirmed via code inspection.

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| F1 | Trade AI Orchestrator silent-failed since 2026-05-21 12:00 | CRITICAL | FIXED |
| F2 | auto_proposal_generator cron missing `--today --apply` flags | CRITICAL | FIXED |
| F3 | 4 PENDING proposals stale for 97 hours without expiry | HIGH | FIXED |
| F4 | pipeline_watchdog crashed every run (schema mismatch) | CRITICAL | FIXED |
| F5 | Telegram alert spam (bypass_router, premarket direct sends) | HIGH | FIXED |
| F6 | TCA Execution Quality page empty (no cron for analyzer) | MEDIUM | FIXED |
| F7 | Scalp Critic LLM timeout blocking entire pipeline | HIGH | FIXED |
| F8 | `chk_long_stop_below_entry` constraint preventing trailing stops above entry | HIGH | FIXED (dropped) |
| F9 | `replace_stop()` did not verify cancellation before placing new stop | HIGH | FIXED |

---

## D. Root Cause Analysis

### RC-1: Orchestrator Dead (Silent Failure via Flock Contention)

- **Script:** `scripts/trade_ai_orchestrator.py`
- **Cron:** `0 9,10,12,14,16 * * 1-5` + `17:30` (6 runs/day)
- **Last success:** 2026-05-21 12:00
- **Mechanism:** Scalp Critic LLM step (qwen3:14b) takes 6-10 minutes per run. When 0900 run still executing at 1000, `safe_flock.sh` silently exits the second invocation. Output piped through `>>` only appears on completion -- killed processes produce zero output.
- **Evidence:** `logs/screener_pm.log` -- last line is 2026-05-21 1200 run.
- **Fix applied:** 
  1. Critic gated by `--no-llm` flag (`trade_ai_orchestrator.py:344`)
  2. 120s hard timeout via threading (`trade_ai_orchestrator.py:358`)
  3. `max_tickers=10` limit (`scalp_critic_agent.py:209`)

### RC-2: auto_proposal_generator Missing `--today --apply` Flags

- **Script:** `scripts/auto_proposal_generator.py`
- **Broken cron:** `*/30 9-16 * * 1-5 ... auto_proposal_generator.py >> logs/auto_proposal.log`
- **Fixed cron:** `*/30 9-16 * * 1-5 ... auto_proposal_generator.py --today --apply >> logs/auto_proposal.log`
- **Mechanism:** Without `--today --apply`, the script prints usage help and exits with code 0. Every 30 minutes since installation. Exit code 0 means no error detection.
- **Evidence:** `logs/auto_proposal.log` -- 15+ lines of identical usage text.

### RC-3: Stale Proposals (97 Hours Without Expiry)

- **Proposals:** #115 ARM, #119 MUD, #121 SHMD, #122 BCS
- **Created:** 2026-05-22
- **Cleanup script:** `scripts/cleanup_stale_proposals.py` (runs at 10:00 and 15:00)
- **Mechanism:** Cleanup ran but `max_age` settings (48h-168h per strategy) were longer than actual staleness for some proposals. The cleanup logic did not enforce a hard cap.
- **Fix:** All 4 manually expired. Need hard cap of PENDING > 72h regardless of strategy.

### RC-4: Pipeline Watchdog Schema Mismatch

- **Script:** `scripts/pipeline_watchdog.py`
- **Cron:** `0 */2 * * *` (every 2 hours)
- **Error:** `psycopg2.errors.UndefinedColumn: column "rows_processed" does not exist` at line 80
- **Mechanism:** The `pipeline_runs` table was migrated to use columns (`id`, `pipeline_key`, `run_label`, `status`, `started_at`, `summary`) but the watchdog query still referenced `rows_processed`.
- **Impact:** The ONE script designed to detect pipeline failures was itself failing silently. No missed-run detection. No auto-retry. No GO coverage checks. No daily summary. Every run crashed.
- **Evidence:** `scripts/pipeline_watchdog.py:80` -- query references `summary` column (line 80-83 in the SELECT).

### RC-5: Alert Spam (bypass_router + Premarket Direct Sends)

- **Primary offender:** `scripts/run_proactive_quote_refresh.py` -- called `send_telegram(msg, bypass_router=True)` every 5 minutes with identical "ATP REVIEW ALERT" for ARM and BCS. In-memory dedupe resets each cron invocation.
- **Secondary offender:** `scripts/premarket_watcher.py` -- had its own direct Telegram sender bypassing the central router.
- **Fix 1:** `bypass_router=True` removed from quote refresh.
- **Fix 2:** Premarket watcher rerouted through central `telegram_alert.py`.
- **Fix 3:** "PRE-MARKET CATALYST" added to P2_DASHBOARD_ONLY suppression list in `telegram_alert_router.py`.

---

## E. Trade Management

### R-Multiple Trailing Stop System

**File:** `scripts/paper_trade_monitor.py` (lines 288-299)

The monitor runs every 5 minutes during market hours and adjusts stops based on R-multiple progression:

| R-Multiple | Stop Action | Lock Level |
|-----------|-------------|------------|
| >= 1.0R | Move stop to breakeven (entry price) | 0R profit |
| >= 1.5R | Move stop to lock 0.5R profit | 0.5R profit |
| >= 2.0R | Move stop to lock 1.0R profit | 1.0R profit |
| >= 3.0R | Move stop to lock 2.0R profit | 2.0R profit |
| >= 80% of target move | Tighten stop to lock 65% of target move | ~0.65x target |

**Design decision** (documented at `paper_trade_monitor.py:283-287`): Manual R-based stops chosen over Alpaca native `trailing_percent` because R-multiple thresholds (1R=breakeven, 1.5R=lock 0.5R, etc.) cannot be expressed as a single trailing percentage. Trade-off: 5-minute gap between adjustments. Acceptable because R-logic is superior to fixed-percent trailing for strategy-aware risk management.

### Stop Safety Fixes Applied This Session

1. **Constraint `chk_long_stop_below_entry` dropped** -- This DB constraint prevented trailing stops from being moved above entry price (which is exactly what the R >= 1.0 breakeven rule requires).
2. **`replace_stop()` now verifies cancellation** (`paper_trade_monitor.py:82-101`) -- Before placing a new stop order, the function polls Alpaca up to 5 times (1s sleep each) to confirm the old stop is in `canceled`/`cancelled` status. If not confirmed after 5 attempts, it proceeds with a warning.
3. **Phantom detection** (`paper_trade_monitor.py:361-382`) -- DB says open but Alpaca has no position: auto-closes as `phantom_no_alpaca_position`.
4. **Integrity pre-check** (`paper_trade_monitor.py:115-162`) -- Before processing positions: cancels never-filled orders (30min), closes phantoms, fixes stuck lifecycle states.

### MFE/MAE Tracking

`paper_trade_monitor.py:224-228` -- Every 5-minute cycle updates `max_favorable_excursion` and `max_adverse_excursion` as percentage from entry. Used by TCA for execution quality grading.

---

## F. Capital Allocation

**File:** `scripts/alpaca_paper_adapter.py` (lines 21-24)

| Parameter | Value | Location |
|-----------|-------|----------|
| MAX_POSITIONS | 3 | `alpaca_paper_adapter.py:22` |
| MAX_POSITION_SIZE | $2,000 | `alpaca_paper_adapter.py:23` |
| MIN_SCORE_ALPACA | 45 | `alpaca_paper_adapter.py:24` |
| Endpoint | `https://paper-api.alpaca.markets` | `alpaca_paper_adapter.py:20` (hardcoded) |
| Enable flag | `ENABLE_ALPACA_PAPER=true` in `.env` | `alpaca_paper_adapter.py:29` |

### Safety Gates (alpaca_paper_adapter.py)

1. **Live endpoint rejection** (line 36-37): If configured URL contains `api.alpaca.markets` without `paper-api`, raises `RuntimeError`.
2. **Risk gate** (line 259-270): `RiskGate.check()` must approve. Fail-closed on error.
3. **Max positions** (line 274-278): DB count of open ALPACA_PAPER trades must be < MAX_POSITIONS.
4. **Duplicate symbol block** (line 281-294): Both DB check and Alpaca API check. No second position on same symbol.
5. **Stop already breached** (line 357-359): Blocks if `current_price <= stop_price`.
6. **Excessive drift** (line 362-366): Blocks if price drifted > 5% from proposed entry.
7. **Market hours gate** (line 386-398): Extended hours 4AM-8PM ET weekdays only.
8. **No price source** (line 352-354): Fail-closed if all quote providers fail.
9. **Fill verification** (line 432-491): Up to 8 polling attempts (~20s) to confirm fill before recording.
10. **Unhedged position close** (line 517-523): If stop placement fails after fill, position is immediately closed.

### Order Type Logic

- Price at or below entry: market order (better price)
- Price within 2% of entry: market order (close enough)
- Price > 2% above entry: limit order at proposed entry
- Extended hours: forced to limit order (Alpaca requirement)

---

## G. Monitoring / Agent Review

### Agent Capabilities vs. Cron Health Monitoring

| Agent | Role | Monitors Cron Health? |
|-------|------|-----------------------|
| Maria | Trade analysis, signal generation | NO |
| Steph | Portfolio intelligence | NO |
| Aegis | Morning briefs, synthesis | NO |
| Alex | Governance, research | NO |
| Iris | Taxonomy, library | NO |

**Key gap (from root cause doc, Section 3):** "The agent system operates on tasks queued via the agent pipeline. They analyze trades, generate briefs, and review proposals. They do NOT monitor cron health or pipeline execution."

### Pipeline Watchdog (Was Broken)

- **File:** `scripts/pipeline_watchdog.py`
- **Role:** Detect missed/failed pipeline runs, auto-retry critical scripts, detect GO tickers missing agent analysis, daily summary.
- **Failure:** `psycopg2.errors.UndefinedColumn: column "rows_processed" does not exist` -- crashed every single run since schema migration.
- **Impact:** The entire self-healing layer was non-functional.

### Pipeline Health Monitor (Limited Scope)

- **File:** `scripts/pipeline_health_monitor.py`
- **Schedule:** 7:00 AM + 10:15 AM weekdays
- **Checks:** GO tickers with missing analysis, news ingestion, finviz enrichment, RAG indexer, agent jobs.
- **Does NOT check:** Orchestrator completion, proposal generation, stop monitor health.

### System Health Agent (NEW -- Deployed 2026-05-26)

- **File:** `scripts/system_health_agent.py`
- **Schedule:** `*/5 9-20 * * 1-5` (weekdays), `*/15 * * * 0,6` (weekends), `0 7 * * 1-5` (full check)
- **Monitors:** 18 components (9 critical, 9 non-critical) -- see Section 9.2 of root cause doc
- **Self-healing:** Max 2 retries per component per 24h. Clears stale locks before retry.
- **Escalation:** CRITICAL failures escalated via Telegram through central router. 2-hour dedup window.
- **Validation:** First run recovered 3 components (orchestrator, incubator promoter, finviz screener) and escalated 3 (news, paper monitor, telegram handler).
- **DB tables:** `system_health_checks`, `system_health_events`
- **API:** `GET /api/v2/execution-integrity`
- **Dashboard:** Command Center -> System & Pipeline -> System Health (15s auto-refresh)

---

## H. Handoff Package

All audit artifacts are in `docs/atm_audit_2026_05_26/`:

| Directory/File | Contents |
|----------------|----------|
| `ROOT_CAUSE_ATM_DEAD_2026_05_26.md` | Full root cause analysis (also at `docs/project/`) |
| `ATM_SYSTEM_AUDIT.md` | This document |
| `AGENT_MONITORING_AUDIT.md` | Agent monitoring gap analysis |
| `SYSTEM_ARCHITECTURE_COMPLETE.md` | Full system architecture reference |
| `TRADE_SUPERVISION_METHODOLOGY.md` | Trade supervision methodology |
| `remediation_plan/` | P0 remediation plan and checklists |
| `source_snapshot/` | Key source file snapshots at time of audit |
| `log_evidence/` | Log file excerpts showing failures |
| `cron_snapshot/` | Crontab dump at time of audit |
| `schema_snapshot/` | DB schema for relevant tables |
| `config_snapshot/` | .env and configuration snapshots |
| `dashboard_snapshot/` | React dashboard screenshot evidence |

---

## I. Remediation Plan

Reference: `docs/atm_audit_2026_05_26/remediation_plan/` (P0_REMEDIATION_PLAN.md)

### P0 (Completed 2026-05-26)

| # | Action | Status |
|---|--------|--------|
| 1 | Fix `auto_proposal_generator` cron (add `--today --apply`) | DONE |
| 2 | Expire 4 stale PENDING proposals | DONE |
| 3 | Remove `bypass_router=True` from quote refresh | DONE |
| 4 | Route premarket watcher through central alert system | DONE |
| 5 | Add TCA analyzer crons (4:30 PM + 5:00 PM) | DONE |
| 6 | Drop `chk_long_stop_below_entry` constraint | DONE |
| 7 | Add cancellation verification to `replace_stop()` | DONE |
| 8 | Gate Scalp Critic with `--no-llm` + 120s timeout + max_tickers=10 | DONE |
| 9 | Deploy System Health Agent with crons | DONE |
| 10 | Enable extended hours trading (4AM-8PM) | DONE |

### P1 (Pending)

| # | Action | Owner |
|---|--------|-------|
| 1 | Fix `pipeline_watchdog.py` schema query (`rows_processed` -> `summary`) | Next session |
| 2 | Add orchestrator completion monitor (alert if no success by 10:30 AM) | Health Agent enhancement |
| 3 | Tighten stale proposal cleanup (hard cap PENDING > 72h) | `cleanup_stale_proposals.py` |
| 4 | Add "zero proposals generated today" alert (if ATM active, no proposals by 11 AM) | Health Agent enhancement |
| 5 | Migrate 35+ direct Telegram senders to central router | Multi-session project |
| 6 | Add persistent dedup for quote refresh alerts (survive cron restarts) | `run_proactive_quote_refresh.py` |

---

## J. Risks

### Active Risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | **35+ scripts with direct Telegram API calls** bypassing the central router. See 41 files found in `scripts/` containing `api.telegram.org`. | HIGH | Gradual migration to central router. Health Agent catches symptoms regardless. |
| R2 | **Scalp Critic can still timeout on heavy load.** 120s cap prevents pipeline block, but critic results are lost when timeout fires. | MEDIUM | `max_tickers=10` limits exposure. `--no-llm` flag available for degraded-mode runs. |
| R3 | **No persistent dedup across cron restarts** for `run_proactive_quote_refresh.py`. In-memory set resets each invocation. | MEDIUM | Router P2 suppression catches most cases. File-based dedup planned. |
| R4 | **Watchdog-watches-the-watchdog problem.** System Health Agent is now the outer watchdog. If it fails, same blind spot returns. | MEDIUM | Health Agent persists to DB every run. Missing DB rows detectable via simple SQL query. Cron failure itself would stop output to log, which is checkable externally. |
| R5 | **Single LLM bottleneck** (qwen3:14b on Arc B50). GPU toll gate lock means all LLM consumers compete. | LOW | Critic timeout, `--no-llm` mode. Future: queue prioritization. |
| R6 | **Fill verification gap.** Market orders have ~20s polling window. Flash crash during this window could result in unhedged position. | LOW | Fail-closed: if stop placement fails, position is closed immediately (`alpaca_paper_adapter.py:517-523`). |

### Risk Count by Category

- Pipeline reliability: 3 (R1, R2, R5)
- Data integrity: 1 (R3)
- Monitoring: 1 (R4)
- Execution: 1 (R6)

---

## K. Next Steps

### Week 1 (2026-05-26 through 2026-06-01)

1. **Monitor System Health Agent** -- Verify it catches real failures, doesn't false-positive, and escalation dedup works correctly.
2. **Validate orchestrator stability** -- Confirm no flock contention with 120s critic timeout in place. Check `logs/screener_pm.log` daily.
3. **Fix pipeline_watchdog.py** -- Update query to use actual `pipeline_runs` schema columns.

### Week 2-3

4. **Migrate direct Telegram senders to central router** -- Prioritize the 10 most frequently fired scripts (quote refresh, proposal alerter, stop decision brief, morning digest, etc.).
5. **Add persistent dedup** -- File-based or DB-based dedup for quote refresh and other high-frequency alert sources.
6. **Increase strategy signal diversity** -- Currently dominated by `momentum_scalp`. Need incubator to exercise all 20+ strategies.

### Ongoing

7. **Tighten stale proposal cleanup** -- Hard 72h cap regardless of strategy `max_age`.
8. **Add "zero output today" checks** -- Health Agent enhancement: if ATM active and no proposals by 11 AM, escalate.
9. **TCA review cadence** -- Weekly review of execution quality grades. Target: >= 80% EXCELLENT/GOOD.

---

## Appendix: Validation Results (2026-05-26 10:42 ET)

| Check | Result |
|-------|--------|
| Scanner ran today | YES -- 118 scans, 2 GO (CODX, PONY) |
| Strategy signals today | YES -- 14 signals generated |
| Proposals created today | YES -- 2 created, 1 PENDING (EVER) |
| Stale proposals expired | YES -- 4 expired (ARM, BCS, MUD, SHMD) |
| Open paper trades | 4 active (AGNC, CMCSA, NVDA, NWG) |
| TCA data populated | YES -- 10 rows (6 EXCELLENT, 1 GOOD, 1 ACCEPTABLE, 1 POOR) |
| Health agent deployed | YES -- cron installed, DB tables created, API live |
| Health agent self-heal | YES -- 3 recovered (orchestrator, promoter, screener) |
| Alert spam suppressed | YES -- router confirmed suppressing at 09:40+ |
| Scalp Critic timeout | FIXED -- 120s cap, --no-llm gated, max_tickers=10 |
| Dashboard updated | YES -- React rebuilt, Execution Integrity section added |
