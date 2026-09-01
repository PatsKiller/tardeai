# POST-FIX SOURCE MANIFEST

Status:      HISTORICAL
as_of:       2026-05-26T15:26:25-04:00
Measured at: efcc51365 / not measured

**Export Timestamp:** 2026-05-26T15:50Z
**Git Commit:** `c1286d314deb377df49713e1646f139db7f43643` (main)
**Git Branch:** `main`
**Export Tool:** Claude Code automated export

---

## Export Summary

| Metric | Count |
|--------|-------|
| **Files exported** | 100 |
| **System state snapshots** | 1 (+ crontab) |
| **Missing expected files** | 1 |
| **Total markdown files** | 102 |

## Missing Expected Files

| File | Status |
|------|--------|
| `config/shared_risk_rules.yaml` | Does not exist at top level. Present at `config/strategies/shared_risk_rules.yaml` (exported) |

---

## Files Exported by Category

### 1. Scheduler / Health / Watchdog (5 files)
- `scripts/safe_flock.sh` (1,379 bytes)
- `scripts/system_health_agent.py` (21,896 bytes)
- `scripts/pipeline_watchdog.py` (10,330 bytes)
- `scripts/pipeline_health_monitor.py` (7,356 bytes)
- `scripts/pipeline_alert.py` (3,833 bytes)

### 2. ATM / Proposal / Orchestrator (6 files)
- `scripts/trade_ai_orchestrator.py` (42,186 bytes)
- `scripts/auto_proposal_generator.py` (45,366 bytes)
- `scripts/atm_auto_approver.py` (23,021 bytes)
- `scripts/cleanup_stale_proposals.py` (3,570 bytes)
- `scripts/incubator_proposal_promoter.py` (37,335 bytes)
- `scripts/scalp_critic_agent.py` (16,104 bytes)

### 3. Execution / Broker / Stop Management (7 files)
- `scripts/alpaca_paper_adapter.py` (41,881 bytes)
- `scripts/paper_trade_monitor.py` (20,702 bytes)
- `scripts/unified_stop_supervisor.py` (10,272 bytes)
- `scripts/strategy_trailing_policy.py` (7,450 bytes)
- `scripts/reconcile_stop_v21_broker_stops.py` (12,246 bytes)
- `scripts/paper_execution_quality.py` (11,763 bytes)
- `scripts/paper_execution_quality_analyzer.py` (11,040 bytes)

### 4. Risk / Capital / Allocation (9 files)
- `scripts/risk_gate.py` (24,158 bytes)
- `scripts/atm_config_manager.py` (5,954 bytes)
- `scripts/cio_decision_engine.py` (9,811 bytes)
- `scripts/live_trading_gate.py` (7,126 bytes)
- `scripts/atm_classifier_health.py` (2,404 bytes)
- `scripts/proposal_decision_gate.py` (8,936 bytes)
- `scripts/proposal_execution_readiness.py` (32,288 bytes)
- `scripts/paper_submit_readiness.py` (9,693 bytes)
- `scripts/monitoring/classifier_health_check.py` (2,200 bytes)

### 5. Alerts / Telegram / Routing (23 files)
- `scripts/telegram_alert.py` (12,253 bytes)
- `scripts/telegram_alert_router.py` (10,473 bytes)
- `scripts/alert_dispatcher_unified.py` (6,873 bytes)
- `scripts/run_proactive_quote_refresh.py` (7,027 bytes)
- `scripts/premarket_watcher.py` (15,095 bytes)
- `scripts/send_telegram_proposal_alert.py` (8,705 bytes)
- `scripts/telegram_callback_handler.py` (26,848 bytes)
- `scripts/telegram_command_handler.py` (116,810 bytes)
- `scripts/telegram_reply_processor.py` (8,562 bytes)
- `scripts/telegram_alert_routing_policy.py` (3,396 bytes)
- `scripts/telegram_proposal_alert_policy.py` (8,026 bytes)
- `scripts/telegram_callback_policy.py` (4,213 bytes)
- `scripts/telegram_smart_alerts.py` (10,136 bytes)
- `scripts/telegram_agent_router_bridge.py` (943 bytes)
- `scripts/telegram_cio_summary.py` (4,518 bytes)
- `scripts/send_morning_brief.py` (6,055 bytes)
- `scripts/send_alert_digest.py` (3,743 bytes)
- `scripts/send_closed_trade_digest.py` (7,719 bytes)
- `scripts/send_no_leads_diagnostic_alert.py` (3,841 bytes)
- `scripts/send_watchpool_maturity_alerts.py` (5,838 bytes)
- `scripts/send_screener_schedule_health_alert.py` (10,143 bytes)
- `scripts/proposal_alerter.py` (16,953 bytes)
- `scripts/simulate_alert_routing.py` (3,316 bytes)

### 5b. Additional Execution/Monitor (5 files)
- `scripts/eod_open_trade_alert.py` (5,854 bytes)
- `scripts/stop_decision_brief.py` (18,058 bytes)
- `scripts/overnight_digest_telegram.py` (5,296 bytes)
- `scripts/morning_digest.py` (10,766 bytes)
- `scripts/proposal_paper_submitter.py` (28,129 bytes)

### 5c. Trade Management (3 files)
- `scripts/open_trade_monitor.py` (30,773 bytes)
- `scripts/open_trade_manager.py` (27,258 bytes)
- `scripts/paper_trade_closer.py` (11,635 bytes)

### 6. Config (35 files)
- `config/atm_config.yaml` (1,695 bytes)
- `config/agent_raci.yaml` (1,401 bytes)
- `config/operator_alert_policy.yaml` (1,989 bytes)
- `config/pipeline_controller.bootstrap.yaml` (7,421 bytes)
- `config/agents.yaml` (6,033 bytes)
- `config/agents.json` (13,694 bytes)
- `config/agent_runtime.json` (3,848 bytes)
- `config/screener_schedule.yaml` (984 bytes)
- `config/llm_fleet_alert_rules.yaml` (552 bytes)
- `config/strategies/shared_risk_rules.yaml` (3,049 bytes)
- `config/strategies/bond_income.yaml` (4,223 bytes)
- `config/strategies/cash_or_stable.yaml` (3,933 bytes)
- `config/strategies/core_growth_compounder.yaml` (4,180 bytes)
- `config/strategies/core_index.yaml` (3,802 bytes)
- `config/strategies/covered_call_income.yaml` (4,641 bytes)
- `config/strategies/defense_thesis.yaml` (4,617 bytes)
- `config/strategies/dividend_growth_compounder.yaml` (4,188 bytes)
- `config/strategies/earnings_catalyst.yaml` (3,839 bytes)
- `config/strategies/earnings_post_momentum.yaml` (5,858 bytes)
- `config/strategies/earnings_pre_buildup.yaml` (5,848 bytes)
- `config/strategies/fib_retracement_bounce.yaml` (6,355 bytes)
- `config/strategies/gap_and_go.yaml` (5,184 bytes)
- `config/strategies/high_yield_income_bdc.yaml` (4,272 bytes)
- `config/strategies/income_add.yaml` (5,832 bytes)
- `config/strategies/international_dividend.yaml` (4,229 bytes)
- `config/strategies/momentum_scalp.yaml` (6,732 bytes)
- `config/strategies/recommendation_schema.yaml` (2,569 bytes)
- `config/strategies/recovery_watch.yaml` (4,538 bytes)
- `config/strategies/reit_income.yaml` (4,237 bytes)
- `config/strategies/sector_rotation.yaml` (5,430 bytes)
- `config/strategies/speculative_growth.yaml` (4,408 bytes)
- `config/strategies/strategy_schema.yaml` (1,214 bytes)
- `config/strategies/swing_breakout.yaml` (5,608 bytes)
- `config/strategies/swing_trade.yaml` (4,414 bytes)
- `config/strategies/tax_loss_harvest.yaml` (4,264 bytes)

### 7. Backend API (1 file)
- `scripts/api_v2.py` (1,035,584 bytes) — implements ALL /api/v2/* endpoints

### 8. Frontend Dashboard (6 files)
- `apps/command-center-v2/src/pages/AutomatedTradeMode.tsx` (31,182 bytes)
- `apps/command-center-v2/src/pages/SystemHealth.tsx` (17,052 bytes)
- `apps/command-center-v2/src/pages/PipelineHub.tsx` (909 bytes)
- `apps/command-center-v2/src/pages/ExecutionQuality.tsx` (9,072 bytes)
- `apps/command-center-v2/src/pages/PaperProposals.tsx` (68,068 bytes)
- `apps/command-center-v2/src/pages/TradeAI.tsx` (42,983 bytes)

### System State
- `SYSTEM_STATE_SNAPSHOT.md` — positions, health checks, events, proposals, execution quality, env vars, ATM mode
- `CRONTAB_EXPORT.md` — full user crontab (~250 entries)

---

## Inventory: Direct Telegram Senders (`send_telegram` / `api.telegram.org`)

64 files contain `send_telegram` calls. 40 files reference `api.telegram.org` directly. 43 files reference `TELEGRAM_BOT_TOKEN`.

### bypass_router Inventory (3 files)

These files bypass the Telegram alert router and send directly:
1. `scripts/send_closed_trade_digest.py`
2. `scripts/system_health_agent.py`
3. `scripts/telegram_alert.py`

### safe_flock Usage Inventory

`safe_flock.sh` is referenced in crontab for these scheduled tasks:
- `atm_auto_approver.py` (ATM lock)
- `unified_stop_supervisor.py` (stop supervisor lock)
- `paper_execution_sweep.py` (paper sweep lock)
- `incubator_proposal_promoter.py` (incubator promoter lock)
- `trade_ai_orchestrator.py` (screener lock, multiple run-labels)
- `alpaca_paper_adapter.py` (Alpaca reconciler lock)
- `portfolio_orchestrator.py` (portfolio lock)

### MAX_POSITIONS / max_concurrent Inventory

| File | Context |
|------|---------|
| `config/atm_config.yaml` | `max_concurrent: 6`, `max_new_per_day: 3` |
| `scripts/alpaca_paper_adapter.py` | Reads max_concurrent for position cap enforcement |
| `scripts/atm_auto_approver.py` | Enforces max_concurrent before auto-approving |
| `scripts/risk_gate.py` | Checks max_concurrent as risk gate condition |
| `scripts/update_docx_session_atm_supply.py` | Docs only |

### classifier_health Inventory

| File | Context |
|------|---------|
| `config/atm_config.yaml` | `min_classifier_health: 0.0` (temporarily lowered from 0.50) |
| `scripts/atm_auto_approver.py` | Checks classifier health gate before approval |
| `scripts/atm_classifier_health.py` | Computes classifier health scores |
| `scripts/atm_config_manager.py` | Reads min_classifier_health threshold |
| `scripts/api_v2.py` | Exposes classifier health in API |
| `scripts/monitoring/classifier_health_check.py` | Cron health check for classifier |
| `scripts/simulate_alert_routing.py` | Test/simulation only |

### time_stop Inventory

Defined in **23 strategy YAML files** under `stop_policy.time_stop` or `max_hold_days`.

Enforced in:
- `scripts/strategy_trailing_policy.py` — reads `time_stop` from strategy config
- `scripts/unified_stop_supervisor.py` — enforces time stop via trailing policy
- `scripts/open_trade_monitor.py` — checks max_hold for alerts
- `scripts/api_v2.py` — exposes time stop data in API

### strategy_trailing_policy Usage Inventory

| File | How Used |
|------|----------|
| `scripts/strategy_trailing_policy.py` | Defines the policy (source of truth) |
| `scripts/unified_stop_supervisor.py` | Imports and applies trailing policy per strategy |
| `scripts/paper_trade_monitor.py` | Imports trailing policy for stop management |

---

## API Endpoint Mapping

All endpoints served by `scripts/api_v2.py` (single 1MB file):

| Endpoint | Frontend Consumer |
|----------|-------------------|
| `/api/v2/atm/status` | AutomatedTradeMode.tsx |
| `/api/v2/atm/strategy-health` | AutomatedTradeMode.tsx |
| `/api/v2/atm/queue-preview` | AutomatedTradeMode.tsx |
| `/api/v2/atm/decisions` | AutomatedTradeMode.tsx |
| `/api/v2/atm/config` | AutomatedTradeMode.tsx |
| `/api/v2/atm/mode` | AutomatedTradeMode.tsx |
| `/api/v2/atm/proposal-action` | AutomatedTradeMode.tsx |
| `/api/v2/execution-integrity` | SystemHealth.tsx |
| `/api/v2/execution-quality` | ExecutionQuality.tsx |
| `/api/v2/paper-proposals` | PaperProposals.tsx |
| `/api/v2/system-health` | SystemHealth.tsx |
| `/api/v2/alerts` | AlertsDashboard.tsx |

---

## Empty Exports

None. All 100 exported files contain source content.

---

## Drive Sync Status

Target: `Trade_AI_Docs_v2/atm_audit_2026_05_26/designer_review/`

Initial sync completed 2026-05-26 17:10Z — 1,552 uploaded, 729 unchanged.
Hourly cron confirmed 2026-05-26 18:05Z — 0 uploaded, 2,286 unchanged, 0 failed.

---

## P0.5 Control Hardening Package (2026-05-26)

Applied on top of the export baseline (`c1286d3`).

### Changes Applied

| Change | File | Status |
|--------|------|--------|
| Observable safe_flock.sh | `scripts/safe_flock.sh` | APPLIED + TESTED |
| gog absolute PATH fix | `scripts/sync-docs-to-drive.py` | APPLIED |

### Designer Replacement Files Created

| File | Scope | Status |
|------|-------|--------|
| `safe_flock.sh.REPLACEMENT.md` | Lock guard observability | APPLIED |
| `sync_docs_drive_cron_wrapper.sh.REPLACEMENT.md` | gog PATH in cron | APPLIED |
| `classifier_health_guardrail_patch.md` | API + dashboard guardrail visibility | APPLIED (P0.5B) |
| `time_stop_enforcement_patch.md` | Review-only time stop surfacing | APPLIED (P0.5B) |
| `alert_routing_migration_patch.md` | Telegram send audit log | APPLIED (P0.5B) |
| `P05_CONTROL_HARDENING_DESIGN_NOTES.md` | Architecture notes for all 5 items | COMPLETE |
| `CLAUDE_APPLY_P05_CONTROL_HARDENING.md` | Step-by-step apply instructions | COMPLETE |

### Backup

`backups/p05_pre_apply_backup_20260526_1500.tgz` (249K) — contains pre-apply
versions of safe_flock.sh, sync-docs-to-drive.py, api_v2.py, ATM config, frontend
pages, and full crontab export.

### safe_flock.sh Event Log

Production events written to `logs/safe_flock_events.jsonl` (JSONL format).
Schema: `ts`, `component`, `event_type`, `severity`, `lock_file`, `pid_file`, `command`, `message`, `exit_code`.
Event types: `started`, `completed`, `lock_skip`, `stale_lock_cleared`.

---

## Safety Confirmation

- **Production files modified:** `safe_flock.sh` (lock guard only), `sync-docs-to-drive.py` (PATH fix only)
- **ATM mode changed:** NO (`manual_kill_switch_only: true`)
- **ALPACA_MODE:** `paper` (unchanged)
- **LLM_DISABLE_LIVE_EXECUTION:** `true` (unchanged)
- **Orders placed:** NONE (paper or live)
- **Crons modified:** NONE
- **Positions opened/closed:** NONE
- **Stop prices modified:** NONE

---

## P0.5B Applied Changes (2026-05-26)

Full report: `P05B_CONTROL_HARDENING_REPORT.md`

| Change | Files | Status |
|--------|-------|--------|
| System Health Agent safe_flock ingestion | `scripts/system_health_agent.py` | APPLIED + TESTED |
| Classifier guardrail API + dashboard | `scripts/api_v2.py`, `AutomatedTradeMode.tsx` | APPLIED |
| Time-stop review surfacing | `scripts/api_v2.py`, `SystemHealth.tsx` | APPLIED (review-only) |
| Direct Telegram sender audit | `scripts/audit_direct_telegram_senders.py` | APPLIED |
| Dashboard trust panel | `SystemHealth.tsx` | APPLIED |
| Telegram audit reports | `reports/direct_telegram_sender_audit.json`, `alert_routing_direct_sender_audit.md` | GENERATED |

### Key Findings

- **Classifier gate:** disabled (0.0) for cold-start burn-in — visible in dashboard
- **Time-stop overdue:** 10 intraday positions held overnight — review-only, no auto-close
- **Telegram audit:** 81 files with refs, 34 direct API callers, 4 bypass risk
- **safe_flock:** 18 events in last hour, 0 skips, clean
- **Frontend:** builds clean (251ms)
- **Safety:** all controls intact, no orders placed
