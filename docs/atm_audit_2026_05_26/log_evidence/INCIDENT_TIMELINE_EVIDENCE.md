# Incident Timeline Evidence -- ATM Audit 2026-05-26

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

## Timeline Summary

| When | Event | Source |
|------|-------|--------|
| 2026-05-21 12:00 | Last successful orchestrator run (v12 complete) | screener_pm.log |
| 2026-05-21 12:00 | Last strategy signals created: 9 inserted, 27 total, 2 GO/A+ scans | screener_pm.log |
| 2026-05-21 14:57 | Last incubator promoter run (0 promoted, 15 skipped) | incubator_promoter.log |
| 2026-05-22 09:00 | Incubator promoter test marker -- last log entry | incubator_promoter.log |
| 2026-05-22 -- 2026-05-25 | **SILENT INTERVAL: No orchestrator runs, no screener runs, no promoter runs** | All logs |
| 2026-05-25 04:00 | First pipeline_watchdog crash (rows_processed column error) | pipeline_watchdog.log |
| 2026-05-26 09:33 | ASPN trailing stop failure (stop $5.81 > entry $5.52 violates constraint) | unified_stop_supervisor.log |
| 2026-05-26 09:36 | ASPN target hit auto-close at $6.01 (target $5.96) -- WIN +1.3R | unified_stop_supervisor.log |
| 2026-05-26 10:35 | Health agent begins recovery: trade_ai_orchestrator retry 1/2 | system_health_agent.log |
| 2026-05-26 10:40 | Trade AI Orchestrator RECOVERED (age=7104.4min stale) | system_health_agent.log |
| 2026-05-26 10:41 | Incubator Promoter RECOVERED (age=5860.0min stale) | system_health_agent.log |
| 2026-05-26 10:41 | Finviz Screener RECOVERED (age=5854.2min stale) | system_health_agent.log |
| 2026-05-26 11:00 | Auto-proposal creates PONY and CODX proposals (proposal ID = None bug) | auto_proposal.log |
| 2026-05-26 11:15 | Health status: 8/24 OK, 8 stale, 1 missing, 4 escalated | system_health_agent.log |

---

## Evidence by Log File

### 1. screener_pm.log -- Last Success

Last orchestrator run completed 2026-05-21 at 12:00. No runs after that.

```
  ✅  strategy_signal_sync      9 inserted  27 total  (2 GO/A+ scans)
  ✅  auto_proposals            6 created  0 skipped  (6 checked)
  ✅  run_summary               run_summary.json saved
  ✅ v12 complete  |  2026-05-21 1200
  GO: INFQ / ARM
```

Log file last modified: 2026-05-21 12:10. No further entries.

### 2. auto_proposal.log -- Usage Spam Evidence

19 consecutive "Usage:" lines with no timestamps -- cron calling the script without required arguments. This means cron was firing but the invocation was broken (missing --today or --run-label flag).

```
Usage: --run-label 1000 or --today or --symbol MNKD
       Add --apply to actually create proposals
Usage: --run-label 1000 or --today or --symbol MNKD
       Add --apply to actually create proposals
[... repeated 19 times total ...]
```

First successful timestamped run: 2026-05-26 10:30:01 (found 0 eligible signals).
Second run at 11:00:01 found 14 eligible, created PONY and CODX but with proposal_id=None bug:

```
2026-05-26 11:00:01,954 [auto_proposal]   PONY: CREATED proposal #None
2026-05-26 11:00:01,995 [auto_proposal] Telegram alert failed for #None: invalid int value: 'None'
```

### 3. pipeline_watchdog.log -- Crash Evidence (Schema Mismatch)

Watchdog crashes repeatedly on column "rows_processed" which does not exist in pipeline_runs. Code also references "script_name" (actual column: pipeline_key).

```
psycopg2.errors.UndefinedColumn: column "rows_processed" does not exist
LINE 1: SELECT id, status, rows_processed FROM pipeline_runs
                           ^
```

This crash repeats in every watchdog invocation from 2026-05-25 04:00 onward.

Recovery attempt at 10:19 (retry finviz_enrichment) and 10:20 (retry incubator_proposal_promoter, incubator_llm_screener). LLM screener timed out after 300s at 10:25.

### 4. system_health_agent.log -- Recovery Evidence

Health agent started 2026-05-26 10:35. Key recovery events:

```
2026-05-26 10:35:01 [health-agent] [retry] trade_ai_orchestrator -- attempt 1/2
2026-05-26 10:40:01 [health-agent] [retry] trade_ai_orchestrator -- attempt 2/2
2026-05-26 10:40:47 [health-agent]   RECOVERED Trade AI Orchestrator  status=RECOVERED  age=7104.4min
2026-05-26 10:41:04 [health-agent]   RECOVERED Incubator Promoter     status=RECOVERED  age=5860.0min
2026-05-26 10:41:45 [health-agent]   RECOVERED Finviz Screener        status=RECOVERED  age=5854.2min
```

Still stale as of 11:15:
- Trade AI Orchestrator: 7144.4 min stale (~4.96 days)
- News Ingestion: 8204.4 min stale (~5.70 days)
- Finviz Enrichment: 6977.0 min stale (~4.84 days)
- Price DB Sync: 8875.0 min stale (~6.16 days)
- Aegis Morning Brief: 8830.0 min stale (~6.13 days)
- TCA Execution Quality: MISSING (never registered)

Final status: 8/24 OK, 8 stale, 1 missing, 0 failed, 0 locked, 3 retried, 4 escalated.

### 5. proactive_quote_refresh_cron.log -- Alert Spam + Suppression

416 "ALERT sent" entries (unsuppressed alerts, mostly 2026-05-20 through 2026-05-25).
20 "Suppressed (P2_DASHBOARD_ONLY)" entries (suppression working as of 2026-05-26).

CODX target_crossed_before_review was the original spam source -- firing every 5 minutes from 2026-05-20 11:00 onward without deduplication.

EVER stop_crossed_pending is the current recurring alert (2026-05-26), now properly suppressed to dashboard-only:

```
2026-05-26 10:40:02 [proactive_quote_refresh]   ALERT sent: EVER stop_crossed_pending [URGENT]
[telegram] Suppressed (P2_DASHBOARD_ONLY): ATP REVIEW ALERT -- STOP CROSSED PENDING
```

### 6. incubator_promoter.log -- Last Run

Last run: 2026-05-22 09:00 (test marker). Last real run: 2026-05-21 14:57.
Result: 0 promoted, 15 skipped. AMPG blocked (no quote data), AIAI skipped (35% spread), GCTS below min price.

### 7. unified_stop_supervisor.log -- ASPN Incident

**Trailing stop failure chain:**

1. Stop adjusted to $5.81 (above entry $5.52):
```
2026-05-26 09:33:06 [stop_supervisor] [ASPN] Stop adjusted to $5.81
```

2. Check constraint violation (stop > entry on a long trade):
```
Paper trade monitor failed: new row for relation "paper_trades" violates check constraint "chk_long_stop_below_entry"
```

3. Auto-recovery: target hit at $6.01, position closed as WIN +1.3R ($273.74 profit):
```
2026-05-26 09:36:07 [stop_supervisor] TARGET HIT: ASPN at $6.01 reached target $5.96 -- auto-closing
2026-05-26 09:36:09 [stop_supervisor] [Iris] ASPN closed WIN +1.3R; unverified catalyst
```

4. Phantom cleanup later:
```
2026-05-26 10:30:10 [stop_supervisor] [integrity] Closed phantom: ASPN id=26 -- not on Alpaca
```

**Additional issues in stop supervisor:**
- Alpaca Data API timeouts throughout the day (AGNC, CMCSA, NVDA, NWG)
- Telegram send failures: "No module named 'telegram_bot'" (recurring)
- agent_intelligence_rules write failed: JSON type mismatch

---

## Root Causes Summary

1. **Orchestrator silent failure (5/22-5/26):** No screener runs for ~5 days. Cron likely stopped or script errored silently.
2. **Watchdog schema mismatch:** pipeline_watchdog.py references `script_name` and `rows_processed` columns that do not exist in `pipeline_runs` (actual: `pipeline_key`, no rows_processed).
3. **Auto-proposal cron misconfiguration:** 19 invocations without required arguments, producing usage spam instead of proposals.
4. **ASPN constraint violation:** Trailing stop moved above entry price ($5.81 > $5.52), violating `chk_long_stop_below_entry`. Position was saved by target hit.
5. **Alert spam (416 unsuppressed):** No deduplication on quote refresh alerts. CODX target_crossed fired every 5 min for days. P2_DASHBOARD_ONLY suppression added but only active for 20 entries on 5/26.
6. **Telegram module missing:** `telegram_bot` module import fails in stop supervisor, blocking all trade closure notifications.
