# System State Snapshot — 2026-05-26T15:50Z

| Field | Value |
|-------|-------|
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Snapshot Time** | 2026-05-26T15:50:33Z |

## Git Log (latest 10)

```
c1286d3 fix: MAX_POSITIONS conflict + strategy-aware trailing stops
242c3f0 audit: Agent Monitoring Audit — completes 12-phase handoff package
3ac554d audit: ATM incident handoff package — 12-phase safety audit
df15b0c fix: ATM pipeline recovery, System Health Agent, 5 root cause fixes
f126ae6 fix: scalp critic aligned with momentum scalp criteria
93be7a9 fix: scalp critic — stop blocking momentum scalp setups on RVOL/float
274b0aa chore: cron-generated strategy configs and governance status refresh
85dda51 ui+api: rich mission drilldown — per-brief threads, agent maturity, timestamps
38b49cb ui: collaboration v3 quality+drilldown + rename Paper Trading → Automated Trading
6ac7bb2 api: add quality metrics, handoff drilldown, RACI health to collaboration endpoint
```

## Git Status

```
?? assets/screeners.yaml.bak_pre_quality_overhaul
?? config/strategies_backup/
?? docs/atm_audit_2026_05_26/designer_review/
?? docs/atm_audit_2026_05_26_FULL_HANDOFF_20260526_1135.tgz
?? docs/openclaw_aegis_morning_brief_2026-05-25.md
?? scripts/deploy_session34_hotfix.py
?? scripts/phase2b_comparison_report.md
?? scripts/phase2b_comparison_results.json
?? scripts/session34_bump_timeouts.py
?? scripts/session34_diagnose.py
?? scripts/session34_fix_covered_call_schema.py
?? scripts/session34_fix_rag_sql.py
?? scripts/session34_queue_triage.py
```

No uncommitted changes to tracked files. All untracked items are audit artifacts or session scripts.

## ATM Mode

- **ATM Config**: `config/atm_config.yaml` — `manual_kill_switch_only: true`
- **ALPACA_MODE** (from .env): `paper`
- **LLM_DISABLE_LIVE_EXECUTION** (from .env): `true`
- **ATM cron**: `*/15 9-15 * * 1-5` via safe_flock + market_day_gate

No `atm_decisions` table exists in the database. ATM mode is controlled by config YAML + env vars.

## Open Paper Positions (20 rows)

| id | symbol | strategy | shares | entry_price | stop_loss | account |
|----|--------|----------|--------|-------------|-----------|---------|
| 5 | XMTR | swing_breakout | 26 | (null) | 72.49 | ALPACA_PAPER |
| 6 | EVC | screener | 390 | (null) | 7.31 | ALPACA_PAPER |
| 21 | INFU | earnings_catalyst | 357 | 8.61 | 7.97 | ALPACA_PAPER |
| 8 | INFU | swing_breakout | 357 | 8.39 | 7.97 | ALPACA_PAPER |
| 11 | FLYW | swing_trade | 171 | 17.51 | 16.63 | ALPACA_PAPER |
| 18 | FLYW | swing_breakout | 171 | 17.51 | 16.63 | ALPACA_PAPER |
| 27 | ASPN | swing_trade | 553 | 5.52 | 5.15 | ALPACA_PAPER |
| 31 | AGNC | reit_income | 293 | 10.22 | 9.71 | ALPACA_PAPER |
| 33 | CMCSA | dividend_growth_compounder | 120 | 24.97 | 23.61 | ALPACA_PAPER |
| 32 | CMCSA | dividend_growth_compounder | 120 | 24.85 | 23.61 | TOS_PAPER |
| 30 | AGNC | reit_income | 293 | 10.22 | 9.71 | TOS_PAPER |
| 29 | NVDA | dividend_growth_compounder | 13 | 218.0 | 210.58 | TOS_PAPER |
| 28 | NWG | dividend_growth_compounder | 189 | 15.84 | 15.05 | TOS_PAPER |
| 26 | ASPN | swing_trade | 553 | 5.42 | 5.15 | TOS_PAPER |
| 24 | FLYW | dividend_growth_compounder | 171 | 16.29 | 15.48 | ALPACA_PAPER |
| 23 | GCTS | momentum_scalp | 1875 | 1.49 | (null) | ALPACA_PAPER |
| 22 | GCTS | momentum_scalp | 1875 | 1.49 | 1.42 | ALPACA_PAPER |
| 20 | GCTS | momentum_scalp | 1875 | 1.49 | 1.42 | ALPACA_PAPER |
| 19 | FLYW | momentum_scalp | 171 | 16.75 | (null) | ALPACA_PAPER |
| 17 | FLYW | swing_breakout | 171 | 17.51 | 16.63 | TOS_PAPER |

## System Health Checks (latest 10)

| id | check_type | component | status | severity | updated_at |
|----|------------|-----------|--------|----------|------------|
| 328 | cron_health | proactive_quote_refresh | OK | INFO | 2026-05-26 11:50 |
| 327 | cron_health | tca_analyzer | MISSING | INFO | 2026-05-26 11:50 |
| 326 | cron_health | pipeline_watchdog | OK | INFO | 2026-05-26 11:50 |
| 325 | cron_health | cleanup_stale_proposals | STALE | INFO | 2026-05-26 11:50 |
| 324 | cron_health | telegram_command_handler | OK | INFO | 2026-05-26 11:50 |
| 323 | cron_health | aegis_morning_brief | STALE | INFO | 2026-05-26 11:50 |
| 322 | cron_health | indicator_engine | OK | INFO | 2026-05-26 11:50 |
| 321 | cron_health | rag_indexer | OK | INFO | 2026-05-26 11:50 |
| 320 | cron_health | price_db_sync | STALE | INFO | 2026-05-26 11:50 |
| 319 | cron_health | finviz_enrichment | STALE | INFO | 2026-05-26 11:50 |

## System Health Events (latest 10)

| id | component | event_type | severity | message |
|----|-----------|------------|----------|---------|
| 134 | news_ingestion | ESCALATION_DEDUPED | CRITICAL | Suppressed duplicate escalation (2h window) |
| 133 | finviz_screener_runner | ESCALATION_DEDUPED | CRITICAL | Suppressed duplicate escalation (2h window) |
| 132 | finviz_screener_runner | RETRY_EXHAUSTED | CRITICAL | Max retries (2) exhausted today |
| 131 | incubator_proposal_promoter | ESCALATION_DEDUPED | CRITICAL | Suppressed duplicate escalation (2h window) |
| 130 | incubator_proposal_promoter | RETRY_EXHAUSTED | CRITICAL | Max retries (2) exhausted today |
| 129 | trade_ai_orchestrator | ESCALATION_DEDUPED | CRITICAL | Suppressed duplicate escalation (2h window) |
| 128 | trade_ai_orchestrator | RETRY_EXHAUSTED | CRITICAL | Max retries (2) exhausted today |
| 127 | news_ingestion | ESCALATION_DEDUPED | CRITICAL | Suppressed duplicate escalation (2h window) |
| 126 | finviz_screener_runner | ESCALATION_DEDUPED | CRITICAL | Suppressed duplicate escalation (2h window) |
| 125 | finviz_screener_runner | RETRY_EXHAUSTED | CRITICAL | Max retries (2) exhausted today |

## Paper Trade Proposals (latest 10)

| id | symbol | strategy_id | signal_decision | created_at |
|----|--------|-------------|-----------------|------------|
| 126 | EVER | swing_trade | (null) | 2026-05-26 10:40 |
| 125 | EVER | speculative_growth | (null) | 2026-05-26 10:37 |
| 124 | EVER | gap_and_go | (null) | 2026-05-22 12:10 |
| 123 | CMCSA | dividend_growth_compounder | (null) | 2026-05-22 09:05 |
| 122 | BCS | dividend_growth_compounder | (null) | 2026-05-22 09:05 |
| 121 | SHMD | swing_trade | (null) | 2026-05-22 09:05 |
| 120 | AGNC | reit_income | (null) | 2026-05-22 09:05 |
| 119 | MUD | recovery_watch | (null) | 2026-05-22 09:05 |
| 118 | NVDA | dividend_growth_compounder | (null) | 2026-05-22 09:05 |
| 117 | NWG | dividend_growth_compounder | (null) | 2026-05-22 09:05 |

## Paper Execution Quality (latest 10)

| id | symbol | strategy_id | fill_quality | slippage_pct | created_at |
|----|--------|-------------|--------------|--------------|------------|
| 10 | ASPN | swing_trade | EXCELLENT | 0.0 | 2026-05-26 09:43 |
| 9 | ASPN | swing_trade | POOR | 1.845 | 2026-05-26 09:43 |
| 8 | NWG | dividend_growth_compounder | EXCELLENT | 0.0 | 2026-05-26 09:43 |
| 7 | NVDA | dividend_growth_compounder | EXCELLENT | 0.0 | 2026-05-26 09:43 |
| 6 | AGNC | reit_income | EXCELLENT | 0.0 | 2026-05-26 09:43 |
| 5 | AGNC | reit_income | EXCELLENT | 0.0 | 2026-05-26 09:43 |
| 4 | CMCSA | dividend_growth_compounder | EXCELLENT | 0.0 | 2026-05-26 09:43 |
| 3 | CMCSA | dividend_growth_compounder | ACCEPTABLE | 0.4829 | 2026-05-26 09:43 |
| 2 | SMX | momentum_scalp | EXCELLENT | 0.0 | 2026-05-07 18:42 |
| 1 | MNKD | gap_and_go | EXCELLENT | 0.0 | 2026-05-07 18:42 |

## Systemd Timers (trade-related)

| Timer | Status |
|-------|--------|
| tradeai-reprice.timer | Active, fires every 15 min |
| tradeai-continuous.timer | Last ran 2026-05-26 04:00 |

## Crontab Summary

Full crontab exported as `CRONTAB_EXPORT.md`. Key ATM-related entries:
- ATM auto-approver: `*/15 9-15 * * 1-5` via safe_flock
- Unified stop supervisor: `*/3 9-16 * * 1-5` via safe_flock
- Paper execution sweep: `*/5 9-16 * * 1-5` via safe_flock
- Incubator promoter: hourly 7-17 via safe_flock
- Orchestrator scoring: 0900, 1000, 1200, 1400, 1600, 1730 via safe_flock
- System health agent: `*/5 9-20 * * 1-5`, `*/15 * * * 0,6`
- Open trade monitor: COMMENTED OUT (STOP-V2.2: replaced by unified_stop_supervisor)
- Paper trade monitor: COMMENTED OUT (STOP-V2.2: replaced by unified_stop_supervisor)
