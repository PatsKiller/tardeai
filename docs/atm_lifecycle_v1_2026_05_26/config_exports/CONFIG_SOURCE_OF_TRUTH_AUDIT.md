# Config Source of Truth Audit

**Generated:** 2026-05-26  
**Git Commit:** `915876f`  

## Config Ownership Map

| Control | Owner File | Enforcing Code |
|---------|-----------|----------------|
| **Max positions (max_concurrent)** | `config/atm_config.yaml` defaults.position_limits.max_concurrent=6 | `atm_auto_approver.py`, `risk_gate.py`, `alpaca_paper_adapter.py` |
| **Max new per day** | `config/atm_config.yaml` defaults.position_limits.max_new_per_day=3 | `atm_auto_approver.py` |
| **Max % per trade** | `config/atm_config.yaml` defaults.position_limits.max_pct_per_trade=0.10 | `atm_auto_approver.py`, `risk_gate.py` |
| **Max % per strategy** | `config/atm_config.yaml` defaults.position_limits.max_pct_per_strategy=25 | `atm_auto_approver.py` |
| **Max % per sector** | `config/atm_config.yaml` defaults.position_limits.max_pct_per_sector=35 | `atm_auto_approver.py` |
| **Classifier health gate** | `config/atm_config.yaml` strategy_filter.min_classifier_health=0.0 | `atm_auto_approver.py`, `atm_classifier_health.py` |
| **Daily loss hard pause** | `config/atm_config.yaml` kill_switches.daily_loss_pct_hard_pause=0.25 | `atm_auto_approver.py` |
| **Operating hours** | `config/atm_config.yaml` operating_hours.start_et/stop_new_entries_et | `atm_auto_approver.py`, `market_day_gate.sh` |
| **Strategy stop policy** | `config/strategies/*.yaml` stop_policy section | `strategy_trailing_policy.py` (hardcoded defaults), YAML overrides |
| **Trailing stop tiers** | `scripts/strategy_trailing_policy.py` TRAILING_TIERS dict | `unified_stop_supervisor.py`, `paper_trade_monitor.py` |
| **Time-stop policy** | `scripts/strategy_trailing_policy.py` time_stop in TRAILING_TIERS | `unified_stop_supervisor.py` (not yet enforced — review-only via P0.5B) |
| **Agent RACI** | `config/agent_raci.yaml` | `api_v2.py` (exposed to dashboard), not enforced in code |
| **Alert routing policy** | `config/operator_alert_policy.yaml` | `telegram_alert_routing_policy.py` |
| **Account routing** | `config/atm_config.yaml` accounts section + DB `accounts` table | `atm_auto_approver.py`, `proposal_paper_submitter.py` |
| **Pipeline schedule** | DB `pipeline_schedule` table + crontab | `pipeline_watchdog.py`, `system_health_agent.py` |
| **Screener schedule** | `config/screener_schedule.yaml` + crontab | `finviz_screener_runner.py` |
| **Same-day skip strategies** | `config/atm_config.yaml` same_day_skip_strategies | `atm_auto_approver.py` |
| **B-1 bucket2 exclusion** | `config/atm_config.yaml` b1_tracking section | `atm_auto_approver.py` |

## Duplication Issues

| Issue | Detail |
|-------|--------|
| **Stop policy split** | Strategy YAMLs define `stop_policy`, but `strategy_trailing_policy.py` has hardcoded TRAILING_TIERS that override/supplement. Two sources of truth. |
| **Time-stop split** | Strategy YAMLs define `max_hold_days`/`time_stop`, `strategy_trailing_policy.py` also defines time_stop per family. Which wins is unclear. |
| **max_concurrent** | Defined in atm_config.yaml both at `defaults` level (6) and `accounts.alpaca_paper` level (6). If they diverge, which wins? |

## Ignored Config Values

| Config | Status |
|--------|--------|
| `agent_raci.yaml` | Exposed in API but not enforced — no code gates on RACI ownership |
| `strategy_filter.whitelist/blacklist` | Both empty `[]`, code reads them but they have no effect |
| `b1_tracking.observation_end: 2026-05-25` | Past date — B-1 observation window has ended but config not updated |

## 35 Config Files Exported

All files exported to `config_exports/` as annotated markdown.
