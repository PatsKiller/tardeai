# Schema Findings -- ATM Audit 2026-05-26

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

## Table Existence

**16 of 19 tables exist:**

| Table | Status | Columns |
|-------|--------|---------|
| pipeline_runs | EXISTS | 11 |
| system_health_checks | EXISTS | 17 |
| system_health_events | EXISTS | 8 |
| paper_trade_proposals | EXISTS | 202 |
| paper_trades | EXISTS | 107 |
| strategy_signals | EXISTS | 47 |
| paper_execution_quality | EXISTS | 34 |
| paper_execution_quality_events | EXISTS | 19 |
| paper_trade_outcome_analytics | EXISTS | 30 |
| trade_ai_scans | EXISTS | 49 |
| incubator_universe | EXISTS | 38 |
| incubator_events | EXISTS | 9 |
| pipeline_schedule | EXISTS | 11 |
| broker_reconciliation_items | EXISTS | 20 |
| alert_dispatch_log | EXISTS | 10 |
| agent_curation_events | EXISTS | 10 |

**3 tables MISSING:**

| Table | Notes |
|-------|-------|
| atm_decisions | Never created -- ATM decision logic may store in pipeline_runs.summary JSONB instead |
| stop_trail_decisions | Never created -- trailing stop decisions stored in paper_trades or stop supervisor logs |
| agent_queue | Never created -- agent task routing may use a different mechanism |

## pipeline_runs Schema (Critical Finding)

The actual columns are:
- id, run_id, pipeline_key, run_label, status, trigger_source, started_at, finished_at, duration_seconds, summary (jsonb), created_at

**Mismatches found in pipeline_watchdog.py (line 80):**
- Code references `script_name` -- column does NOT exist (actual: `pipeline_key`)
- Code references `rows_processed` -- column does NOT exist (no equivalent column; row counts live in `summary` JSONB)

This schema mismatch is the direct cause of the watchdog crash loop observed in logs starting 2026-05-25 04:00.

## Other Notable Schema Observations

- paper_trade_proposals has 202 columns -- extremely wide table, likely accumulated from iterative feature additions
- paper_trades has 107 columns with a check constraint `chk_long_stop_below_entry` that caused the ASPN trailing stop failure (stop $5.81 > entry $5.52)
- pipeline_runs.status defaults to 'created' -- lifecycle is created -> running -> completed/failed
