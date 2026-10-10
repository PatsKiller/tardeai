Status:      ACTIVE
as_of:       2026-10-09T23:00:06-04:00
Measured at: main c4782f219 / live b7dbe6e60-main-exact-phase2-20261009-210323

# Cron inventory — system of record: column specification (v1, 2026-10-09 21:55 ET)

Operator mandate (2026-10-09 ~21:50 ET): no cron job is migrated, modified, disabled, consolidated or retired
until it is documented, classified, reviewed and approved here. One row per **scheduled unit**: each live crontab
line, each scheduled user/system timer, each health-tick step, and each n8n workflow that schedules work.
Commented/RETIRED crontab lines are listed with `active=no` so retirements stay auditable.

Evidence rule: every factual cell is derived from code, crontab, unit files, the lane registry, logs, receipts,
the coordination ledger or the database. A judgement cell (purpose, classification, complexity, risk, priority)
cites its basis in `evidence_notes`. Unknown is written `UNKNOWN`, never guessed.

## Identity and schedule (machine-derived)
| column | meaning |
|---|---|
| `inv_id` | stable id: `cron:L<line>`, `timer:<unit>`, `tick:<step>`, `n8n:<workflow_id>` |
| `job_name` | lane_id from the registry if matched, else the script name |
| `source` | crontab / systemd-user-timer / systemd-system-timer / health-tick / n8n |
| `active` | yes / no (commented, disabled, RETIRED) |
| `server_env` | host (ms01-openclaw) and env: production (CURRENT release) / dev-tree / lab / n8n-lab |
| `schedule_expr` | raw cron expression or OnCalendar |
| `frequency_per_day` | computed fires per weekday (and weekend if different) |
| `timezone` | the cron/timer TZ in force |
| `command` | the command line, secrets masked |
| `script_path` | primary script |
| `registry_row` | matching `config/lane_registry.json` lane_id or NONE |
| `lock` | flock/safe_flock lock path or NONE |
| `wrapper` | market_day_gate / offpeak / peak wrapper / timeout / none |

## Function and data flow (code-derived + judgement)
| column | meaning |
|---|---|
| `purpose` | one-sentence business function |
| `business_function` | trading-adjacent / portfolio data / research / alerts-ops / monitoring / maintenance / reporting / governance / other |
| `dependencies` | services, DB tables, APIs, other jobs it requires |
| `triggers_inputs` | what it reads (tables, files, APIs, queues) |
| `outputs_downstream` | what it writes and who consumes it |
| `owner_stakeholder` | registry owner/agent, else UNKNOWN |
| `error_handling` | exit-code honesty (honest / exits-0-on-failure / unknown), retries, logging |
| `notification_method` | none / log only / health-tick / fan-in incident / send_telegram / email / other |

## Runtime (evidence)
| column | meaning |
|---|---|
| `log_path` | where its output goes |
| `last_run` | newest evidence of a run (timestamp) |
| `last_success` | newest evidence of a successful run |
| `runs_7d` / `failures_7d` / `failure_rate_7d` | from logs/receipts/ledger; UNKNOWN when no durable signal |
| `known_issues` | measured defects (cite) |
| `usage_status` | ACTIVE-USED / ACTIVE-NO-CONSUMER / IDLE (fires, does nothing) / NEVER-RUNS / FAILING / OBSOLETE |

## Migration assessment
| column | meaning |
|---|---|
| `can_migrate` | yes / no / conditional |
| `should_migrate` | yes / no |
| `must_remain_outside_n8n` | yes (with reason: broker/order/secret/daemon §23.14, watchdog-of-n8n, etc.) / no |
| `blockers` | what prevents migration today |
| `n8n_equivalent` | dispatcher lane (§23.11) / event-router lane / per-lane workflow / heartbeat-watched only |
| `custom_work_required` | code changes needed first (dry-run flag, receipt, exit codes, lock, allowlist argv) |
| `tests_required` | what must be proven before shadow/canary/cutover |
| `classification` | exactly one of: **Ready for Migration · Requires Refactoring Before Migration · Requires Custom Development · Not Recommended for Migration · Retain as Existing Cron Job · Candidate for Retirement** |
| `proposed_n8n_workflow_name` | dispatcher row name (`<lane_id>` under the dispatcher) or per-lane workflow name |
| `proposed_n8n_workflow_id` | generic workflow id (dispatcher) or INDEX.json id, else TBD |
| `migration_complexity` | Low / Medium / High |
| `migration_risk` | Low / Medium / High / Critical |
| `migration_priority` | P1 / P2 / P3 / P4 |
| `migration_status` | Not started / Documented / Approved / Shadow / Canary / Cut over / Validated / Blocked / Retired / Consolidated |
| `validation_status` | Not validated / Dry-run proven / Shadow receipts / Canary receipts / Natural-schedule proven |
| `cutover_status` | Not cut over / Cut over (date, receipt) |
| `rollback_plan` | Yes (how) / No |
| `consolidation_group` | id of the merge/pipeline group it belongs to, if any |
| `rationalization_rec` | F_rationalization recommendation (as-is), for comparison |
| `approval_status` | **Pending review** for every row until the operator approves |
| `evidence_notes` | citations for every judgement |
