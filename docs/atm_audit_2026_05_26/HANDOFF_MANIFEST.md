# ATM Audit Handoff Manifest

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

**Timestamp:** 2026-05-26T11:15:00Z
**Git Branch:** main
**Git Commit:** df15b0c (fix: ATM pipeline recovery, System Health Agent, 5 root cause fixes)
**Git Status:** Clean (11 untracked pre-existing artifacts)
**Hostname:** ms01-openclaw
**Operator:** johnclaw

---

## Package Contents

### Source Snapshot (215 files)
Scripts matching: *atm*, *proposal*, *orchestrator*, *scalp*, *critic*, *paper*, *trade*, *stop*, *trailing*, *execution*, *quality*, *tca*, *watchdog*, *health*, *alert*, *telegram*, *alpaca*, *allocation*, *sizing*, *strategy*, *incubator*, *promoter*
Frontend pages: AutomatedTradeMode, PaperProposals, ExecutionQuality, SystemHealth, TradeAI, PipelineHub, PaperStatus

### Config Snapshot (9 files)
Strategy YAMLs, pipeline bootstrap, operator alert policy, ATM config

### Cron Snapshot
- `crontab_current.txt` — 337 lines, 181 active jobs
- `ATM_CRON_MAP.md` — Key ATM/pipeline job documentation

### Schema Snapshot
- `table_schemas.md` — 19 table schemas (16 found, 3 missing)
- `SCHEMA_FINDINGS.md` — Mismatch analysis, migration gaps

### Log Evidence
- `INCIDENT_TIMELINE_EVIDENCE.md` — 5/21-5/26 incident timeline with log excerpts

### API Samples (12 files)
All captured from localhost:7777. No secrets exposed.
- atm_status, atm_strategy_health, atm_queue_preview, atm_decisions
- atm_config (redacted), execution_quality, execution_integrity
- paper_proposals, paper_status, system_health, cron_health, trade_ai_overview
- `API_CAPTURE_SUMMARY.md`

### Audit Documents
- `ATM_SYSTEM_AUDIT.md` — Full system audit (Sections A-K)
- `STOP_AND_TRADE_MANAGEMENT_AUDIT.md` — Stop/trailing logic per strategy
- `CAPITAL_ALLOCATION_AUDIT.md` — Sizing, caps, account routing
- `AGENT_MONITORING_AUDIT.md` — Agent coverage gaps

### Remediation Plan
- `P0_REMEDIATION_PLAN.md` — 8 P0 items, implementation status

### Reference Documents (copied)
- ROOT_CAUSE_ATM_DEAD_2026_05_26.md
- CURRENT_PROJECT_CONTEXT.md
- SYSTEM_ARCHITECTURE_COMPLETE.md
- TRADE_SUPERVISION_METHODOLOGY.md
- PROJECT_DOC_INDEX.md
- MONDAY_BURNIN_CHECKLIST.md

### Safety Snapshot
- `backups/safety_snapshot.txt` — Full safety state at audit start
- `backups/pre_atm_audit_source_backup_20260526_1110.tgz` — Pre-audit source backup

---

## Redaction Notes
- .env file excluded from all snapshots
- API keys, tokens, passwords never captured
- ATM config API response captured as-is (no secrets in response)
- Telegram bot token never included

## Known Risks
1. 35+ scripts send Telegram directly bypassing central router
2. Scalp Critic can still timeout on heavy LLM contention (mitigated by 120s cap)
3. In-memory alert dedup resets per cron invocation (no persistent dedup)
4. safe_flock.sh silently skips without logging
5. 3 expected tables don't exist (atm_decisions, stop_trail_decisions, agent_queue)

## Missing Expected Files
- docs/operator/ATM_RUNBOOK.md — does not exist
- Dashboard screenshots — Playwright not available in this session

## Confirmation
- Live trading: BLOCKED (ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true)
- ATM mode: NOT CHANGED
- No live orders placed
- No .env modifications
- No broker credential changes
