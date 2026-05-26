# Agent Monitoring Audit — 2026-05-26

**Scope:** Every agent, monitor, and watchdog component in the system. Why none of them caught the 4-day ATM outage.  
**Date:** 2026-05-26  
**Reference:** `docs/project/ROOT_CAUSE_ATM_DEAD_2026_05_26.md` Section 3  

---

## 1. Agent Inventory

### 1.1 Maria — Trade Analysis Agent

| Attribute | Value |
|-----------|-------|
| Role | Trade analysis, signal generation, thesis authoring |
| Monitors cron health? | **NO** |
| Monitors pipeline execution? | **NO** |
| What it does | Analyzes individual tickers queued via agent pipeline. Produces trade theses, signal quality reviews, and enrichment commentary. |
| What it does NOT do | Check whether the orchestrator ran. Check whether proposals were generated. Check whether stops are being monitored. |
| Relevant to outage? | Maria would have generated analysis IF the orchestrator produced GO signals. Since the orchestrator was dead (RC-1), Maria had no work queued. Maria cannot detect "no work was queued today." |

### 1.2 Steph — Portfolio Intelligence Agent

| Attribute | Value |
|-----------|-------|
| Role | Portfolio analytics, position review, income tracking |
| Monitors cron health? | **NO** |
| Monitors pipeline execution? | **NO** |
| What it does | Runs portfolio-level analysis: position sizing review, income attribution, sector exposure, risk metrics. |
| What it does NOT do | Check pipeline freshness. Detect stale proposals. Monitor broker connectivity. |
| Relevant to outage? | Steph would have flagged portfolio anomalies (e.g., zero new positions) in a weekly synthesis, but does not run intraday health checks. The 4-day gap fell within normal variance for a quiet trading week. |

### 1.3 Aegis — Morning Brief / Synthesis Agent

| Attribute | Value |
|-----------|-------|
| Role | Daily morning brief generation, market synthesis, overnight event summary |
| Monitors cron health? | **NO** |
| Monitors pipeline execution? | **NO** |
| Schedule | `5 8 * * 1-5` (8:05 AM weekdays) |
| Log | `logs/aegis_brief.log` |
| What it does | Compiles market context, overnight developments, sector moves, and position status into a morning brief delivered via Telegram. |
| What it does NOT do | Check if the orchestrator completed. Check if proposals exist. Verify pipeline health. |
| Relevant to outage? | Aegis morning briefs ran normally during the outage. The brief reports on market context and existing positions, not on whether the pipeline generated new signals. A brief saying "no new GO signals today" is indistinguishable from a quiet market day. |

### 1.4 Alex — Governance / Research Agent

| Attribute | Value |
|-----------|-------|
| Role | Research tasks, governance review, document generation |
| Monitors cron health? | **NO** |
| Monitors pipeline execution? | **NO** |
| What it does | Handles research queries, generates governance reports, reviews strategy compliance. Task-driven (queued via agent pipeline). |
| What it does NOT do | Proactively check system health. Detect pipeline breaks. Monitor cron schedules. |
| Relevant to outage? | Alex had no governance alerts because no proposals were generated (RC-2). No proposals = no governance review needed = no anomaly detected. |

### 1.5 Iris — Taxonomy / Library Agent

| Attribute | Value |
|-----------|-------|
| Role | Content taxonomy, knowledge library curation, document classification |
| Monitors cron health? | **NO** |
| Monitors pipeline execution? | **NO** |
| What it does | Classifies and indexes documents, maintains knowledge graph, curates the research library. |
| What it does NOT do | Monitor any operational component. Detect pipeline failures. |
| Relevant to outage? | Iris is a knowledge management agent with no operational monitoring responsibility. |

---

## 2. Monitor Inventory

### 2.1 System Health Agent (NEW — Deployed 2026-05-26)

| Attribute | Value |
|-----------|-------|
| File | `scripts/system_health_agent.py` |
| Role | Execution integrity monitoring for all pipeline components |
| Monitors cron health? | **YES** |
| Components monitored | 18 (9 critical, 9 non-critical) |
| Schedule | `*/5 9-20 * * 1-5`, `*/15 * * * 0,6`, `0 7 * * 1-5` |
| Self-healing | Yes -- max 2 retries per component per 24h |
| Escalation | Via central Telegram router (NO bypass). 2-hour dedup window. |
| DB tables | `system_health_checks`, `system_health_events` |
| API | `GET /api/v2/execution-integrity` |

**Monitored components** (from `system_health_agent.py:33-123`):

| Component | Critical | Max Age (min) | Has Retry Cmd | Downstream Impact |
|-----------|----------|---------------|---------------|-------------------|
| trade_ai_orchestrator | YES | 180 | YES | signals, proposals, ATM |
| auto_proposal_generator | YES | 60 | YES | proposals, ATM |
| incubator_proposal_promoter | YES | 180 | YES | incubator proposals |
| finviz_screener_runner | YES | 1500 | YES | scanner input |
| news_ingestion | YES | 480 | NO | catalyst detection |
| unified_stop_supervisor | YES | 10 | YES | trailing stops |
| telegram_command_handler | YES | 5 | NO | operator commands |
| pipeline_watchdog | YES | 150 | NO | self-healing |
| alpaca_reconciler | no | 1500 | NO | DB-broker sync |
| finviz_enrichment | no | 1500 | NO | enriched data |
| price_db_sync | no | 1500 | NO | price freshness |
| rag_indexer | no | 300 | NO | agent context |
| indicator_engine | no | 1500 | NO | technical indicators |
| aegis_morning_brief | no | 1500 | NO | daily brief |
| cleanup_stale_proposals | no | 1500 | NO | proposal hygiene |
| tca_analyzer | no | 1500 | NO | execution quality |
| proactive_quote_refresh | no | 15 | NO | quote freshness |

**How it works** (4-step process per component):

1. **Log freshness check** (`_check_log_freshness`, line 158-176): Reads file mtime, compares to `max_age_min`. Status: OK / STALE / MISSING / ERROR.
2. **Lock contention check** (`_check_lock_contention`, line 179-201): Reads `.pid` file, checks `/proc/{pid}` liveness. Detects stale locks (dead PID).
3. **Output validity check** (`_check_output_validity`, line 204-224): Reads last 2KB of log. Detects "Usage:" errors (RC-2 pattern), Python tracebacks, excessive ERROR lines.
4. **Self-heal** (`_attempt_retry`, line 229-280): Clears stale locks, runs retry command, logs result. Max 2/day.

**First-run validation** (2026-05-26 10:29-10:38):
- Dry run: 7/18 OK, 8 stale, 3 missing
- Active run: 3 auto-recovered (orchestrator, incubator promoter, finviz screener)
- 3 escalated to operator (news ingestion, paper monitor, telegram handler)
- Orchestrator produced 118 scans, 2 GO, 14 strategy signals within minutes of recovery

### 2.2 Pipeline Watchdog (Broken During Outage)

| Attribute | Value |
|-----------|-------|
| File | `scripts/pipeline_watchdog.py` |
| Role | Detect missed/failed pipeline runs, auto-retry, daily summary |
| Schedule | `0 */2 * * *` (every 2 hours) |
| Status during outage | **CRASHED EVERY RUN** |
| Error | `psycopg2.errors.UndefinedColumn: column "rows_processed" does not exist` |
| Location | `pipeline_watchdog.py:80` -- query references `summary` in SELECT from `pipeline_runs` |

**What the watchdog was supposed to do:**
1. Query `pipeline_schedule` for active scheduled scripts (line 71)
2. Check `pipeline_runs` for completion within expected window (line 80-83)
3. Auto-retry critical scripts up to 3 times (line 103)
4. Send Telegram alerts for missed/failed runs (line 32-42)
5. Detect GO tickers missing agent analysis
6. Generate 8:30 AM daily summary

**Why it was broken:** The `pipeline_runs` table schema was migrated. Old columns like `rows_processed` no longer exist. The watchdog query was not updated to match. Every single execution since the migration crashed immediately at the first DB query.

**Direct Telegram sends:** `pipeline_watchdog.py:32-42` has its own `send_telegram()` function that calls `api.telegram.org` directly, bypassing the central router. This is one of 41 scripts with direct Telegram API calls.

### 2.3 Pipeline Health Monitor (Limited Scope)

| Attribute | Value |
|-----------|-------|
| File | `scripts/pipeline_health_monitor.py` |
| Role | Check GO ticker intelligence coverage |
| Schedule | 7:00 AM + 10:15 AM weekdays |

**What it checks** (from `check_morning_pipeline`, line 29-47):
- News ingestion: >= 3 articles in last 4 hours
- Finviz enrichment: recent updates to watchlist
- RAG indexer: recent content embeddings
- Agent jobs: recent `watchlist_agent_results`

**What it does NOT check:**
- Orchestrator completion
- Proposal generation
- Stop monitor health
- Auto-approver function
- Broker connectivity

**Gap:** This monitor verifies data pipeline freshness but has zero visibility into the execution pipeline (orchestrator -> proposals -> ATM -> broker). It would not have detected RC-1, RC-2, or RC-3.

---

## 3. Root Cause: Why No Agent/Monitor Caught the Outage

### Q1: Why didn't any agent catch the orchestrator being dead?

**Answer:** Agents (Maria, Steph, Aegis, Alex, Iris) do not monitor cron health or pipeline execution. They are task-driven: they process work items queued via the agent pipeline. When the orchestrator stopped producing GO signals (RC-1), no new work was queued for Maria. No new proposals meant no governance work for Alex. Aegis briefs ran normally but report on market context, not pipeline health. Steph monitors portfolio metrics, not cron schedules.

The pipeline watchdog (`pipeline_watchdog.py`) was supposed to detect this, but it was crashing on every run due to the schema mismatch (RC-4). The pipeline health monitor (`pipeline_health_monitor.py`) only checks data freshness at 7:00 AM and 10:15 AM -- it does not check whether the orchestrator completed a run.

**Evidence:** Root cause doc Section 3: "The agent system operates on tasks queued via the agent pipeline. They analyze trades, generate briefs, and review proposals. They do NOT monitor cron health or pipeline execution."

### Q2: Why didn't any agent catch the missing proposals?

**Answer:** The `auto_proposal_generator.py` was invoked every 30 minutes but printed usage help and exited with code 0 (RC-2). From the system's perspective, the script "ran successfully" every time -- exit code 0, output produced, no crash. The output was usage text, not an error. No component checks whether the auto_proposal_generator produced actual proposals vs. usage help.

The pipeline health monitor does not check proposal generation. The watchdog was broken. No agent has a "there should be proposals by now" check.

**Evidence:** `logs/auto_proposal.log` -- 15+ lines of identical usage text. `auto_proposal_generator.py:8-11` shows the required flags: `--today --apply` or `--run-label XXXX --apply`.

### Q3: Why didn't any agent catch the stale proposals (97h PENDING)?

**Answer:** The `cleanup_stale_proposals.py` ran at 10:00 and 15:00 daily but used per-strategy `max_age` thresholds that were too loose (48h-168h). The proposals were stale by human standards (97 hours) but within the programmatic thresholds for some strategies.

No agent monitors proposal age. Maria reviews proposals for trade quality, not staleness. Alex handles governance but only when triggered by specific events, not by periodic proposal age scans.

**Evidence:** Root cause doc RC-3: "Cleanup ran but didn't expire them -- the proposals' max_age settings (48h-168h depending on strategy) were longer than the actual staleness."

### Q4: Why wasn't the watchdog crash detected?

**Answer:** The watchdog IS the detector. It is the component responsible for detecting failures in other components. When it crashes, nothing detects the crash because there is no meta-watchdog monitoring the watchdog itself.

This is the classic "who watches the watchmen?" problem. The watchdog's own crash produced a Python traceback in its log file, but:
- No other script reads the watchdog's log
- The watchdog's cron (piped to log file) does not check exit codes
- The pipeline health monitor does not check watchdog health
- No agent monitors watchdog status

**Evidence:** `pipeline_watchdog.py:80` -- the failing query. The error `psycopg2.errors.UndefinedColumn` would appear in `logs/pipeline_watchdog.log` but nobody reads that file.

### Q5: Why did the system appear healthy on the surface?

**Answer:** Multiple factors created a false sense of health:

1. **Crons fired on schedule** -- All 181 cron jobs ran. The issue was that some produced no useful output (orchestrator killed by flock, proposal generator printed help).
2. **No crash alerts** -- The scripts that crashed (watchdog) did so silently (output to log file only). The scripts that failed functionally (proposal generator) exited with code 0.
3. **Alert spam masked real issues** -- The quote refresh script sent "ATP REVIEW ALERT" every 5 minutes, creating the illusion of an active system. Operator could reasonably assume "the system is alerting me, so it must be running."
4. **Morning briefs ran normally** -- Aegis briefs reported market context and existing positions. "No new signals" looks the same as a quiet market.
5. **Dashboard showed existing positions** -- The 4 open trades (AGNC, CMCSA, NVDA, NWG) continued to display correctly. The dashboard does not show "days since last new signal."

---

## 4. Monitoring Gap Analysis

### Before (2026-05-25)

```
Pipeline Component          Monitored By              Status
─────────────────────────── ───────────────────────── ─────────
Orchestrator completion     pipeline_watchdog          BROKEN (RC-4)
Proposal generation         (nothing)                  GAP
Stale proposal cleanup      cleanup_stale_proposals    TOO LOOSE
Stop monitoring health      (nothing)                  GAP
Broker connectivity         (nothing)                  GAP
Alert router function       (nothing)                  GAP
Watchdog self-health        (nothing)                  GAP
Data pipeline freshness     pipeline_health_monitor    OK (limited)
GO ticker coverage          pipeline_health_monitor    OK
```

### After (2026-05-26)

```
Pipeline Component          Monitored By              Status
─────────────────────────── ───────────────────────── ─────────
Orchestrator completion     system_health_agent        ACTIVE (180min max age)
Proposal generation         system_health_agent        ACTIVE (60min max age)
Stop monitoring health      system_health_agent        ACTIVE (10min max age)
Broker connectivity         system_health_agent        ACTIVE (via alpaca_reconciler)
Alert router function       system_health_agent        ACTIVE (via telegram_command_handler)
Watchdog self-health        system_health_agent        ACTIVE (150min max age)
Data pipeline freshness     system_health_agent + PHM  ACTIVE (dual coverage)
GO ticker coverage          pipeline_health_monitor    OK
Stale proposal cleanup      cleanup_stale_proposals    NEEDS TIGHTENING
"Zero output today" check   (planned)                  GAP - P1 enhancement
```

---

## 5. New Monitors Deployed / Required

### Deployed: System Health Agent

- **Status:** ACTIVE as of 2026-05-26 10:40 ET
- **File:** `scripts/system_health_agent.py`
- **Evidence:** First active run recovered 3 components and escalated 3 to operator
- **Coverage:** 18 components, 9 critical
- **Self-healing:** Auto-retry with max 2/day per component
- **Persistence:** Results written to `system_health_checks` and `system_health_events` tables

### Required: Orchestrator Completion Check

- **Status:** COVERED by health agent (trade_ai_orchestrator max_age_min=180)
- **Enhancement needed:** Alert if no successful orchestrator run by 10:30 AM specifically (not just max age)

### Required: Proposal Generation Check

- **Status:** COVERED by health agent (auto_proposal_generator max_age_min=60)
- **Enhancement needed:** Health agent checks log freshness but not whether proposals were actually created. A "zero proposals today by 11 AM" check would catch RC-2-style failures where the script runs but produces no proposals.

### Required: Persistent Dedup

- **Status:** NOT DEPLOYED
- **Gap:** `run_proactive_quote_refresh.py` and similar high-frequency scripts use in-memory dedup that resets each cron invocation. Need file-based or DB-based dedup.

### Required: Watchdog Schema Fix

- **Status:** NOT DEPLOYED (P1)
- **Gap:** `pipeline_watchdog.py` still references `rows_processed`. Needs update to match current `pipeline_runs` schema.

---

## 6. Direct Telegram API Bypass Audit

**41 scripts** in `scripts/` contain direct calls to `api.telegram.org`, bypassing the central alert router (`scripts/telegram_alert.py` and `scripts/telegram_alert_router.py`).

### Fixed This Session

| Script | Issue | Fix |
|--------|-------|-----|
| `run_proactive_quote_refresh.py` | `bypass_router=True` | Removed bypass flag |
| `premarket_watcher.py` | Own Telegram sender | Rerouted through central alert system |
| `telegram_alert_router.py` | Missing PRE-MARKET CATALYST suppression | Added to P2_DASHBOARD_ONLY list |

### Remaining (35+ scripts)

Notable direct senders that should be migrated to central router:

| Script | Frequency | Priority |
|--------|-----------|----------|
| `pipeline_watchdog.py` | Every 2h (when working) | HIGH -- has its own `send_telegram()` function |
| `proposal_alerter.py` | On new proposals | HIGH -- operator-facing |
| `send_telegram_proposal_alert.py` | On approvals | HIGH -- operator-facing |
| `eod_open_trade_alert.py` | Daily 4:15 PM | MEDIUM |
| `stop_decision_brief.py` | On stop events | MEDIUM |
| `morning_digest.py` | Daily 8 AM | MEDIUM |
| `portfolio_alerts.py` | On threshold breach | MEDIUM |
| `scalp_critic_agent.py` | On critic findings | LOW |
| `pipeline_health_monitor.py` | 7 AM + 10:15 AM | LOW |
| `pipeline_alert.py` | On pipeline failures | LOW |

**Risk:** Direct senders bypass classification, dedup, and suppression. A malfunctioning script can flood the operator with alerts (as happened with RC-5). Central router provides P0-P3 classification, suppression lists, and dedup windows.

---

## 7. Recommendations

### Immediate (This Week)

1. **Monitor System Health Agent daily** -- Review `system_health_events` table and `/api/v2/execution-integrity` dashboard page. Confirm no false positives or missed failures.
2. **Fix pipeline_watchdog.py** -- Update `rows_processed` references to `summary` in the SELECT query.
3. **Tighten stale proposal cleanup** -- Add hard 72h PENDING cap in `cleanup_stale_proposals.py`.

### Short-Term (2 Weeks)

4. **Add "zero output" health checks** -- Enhancement to system_health_agent.py: check DB for actual output (proposals created, signals generated) not just log freshness.
5. **Migrate top 5 direct Telegram senders** to central router (pipeline_watchdog, proposal_alerter, send_telegram_proposal_alert, eod_open_trade_alert, stop_decision_brief).
6. **Implement persistent dedup** -- DB-backed dedup table for high-frequency alert sources. Schema: `(source, message_hash, sent_at)` with TTL cleanup.

### Long-Term (1 Month)

7. **Agent monitoring capability** -- Consider adding a "system health" task type to the agent pipeline so Maria or a dedicated agent can interpret health data, correlate failures, and produce natural-language diagnostics.
8. **Full Telegram sender migration** -- All 41 scripts using central router. Zero direct API calls outside `telegram_alert.py`.
9. **Health Agent redundancy** -- If the health agent itself fails, a lightweight cron (single SQL query against `system_health_checks` for last-check-age) can detect the gap and send a bare Telegram alert.
