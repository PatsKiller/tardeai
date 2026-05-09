# Project Documentation Index

**Updated:** 2026-05-09 (Post-Session 35)

## Read First

1. `docs/project/SYSTEM_FACTS_LATEST.md` — Current system facts
2. `docs/project/POST_HARDENING_CHECKPOINT_20260509.md` — System baseline
3. `docs/MASTER_SYSTEM_DOCUMENTATION.md` — Full system documentation
4. `docs/ARCHITECTURE_OVERVIEW.md` — Architecture diagram and overview
5. `docs/project/SESSION35_PHASE1_CRON_MIGRATION_OBSERVABILITY.md` — Latest operational change
6. `docs/project/SESSION34_PIPELINE_CONTROLLER_LIVE_RUN_AND_OPERATIONAL_READINESS.md` — Operational readiness
7. `docs/project/SESSION32_UNIFIED_SELF_IMPROVEMENT_COMMAND_CENTER.md` — Operator dashboard

## Current Session Docs

| Session | Doc | Focus |
|---------|-----|-------|
| 27 | SESSION27_TCA_RECON_INTRATRADE_INTELLIGENCE.md | TCA, broker recon, open trade intelligence |
| 27B | EXECUTION_TIME_REVALIDATION_20260509.md | Universal execution-time revalidation |
| 28 | SESSION28_LEARNING_GOVERNANCE.md | Learning governance control plane |
| 29 | SESSION29_AGENT_CALIBRATION_ENGINE.md | Agent calibration and outcome linking |
| 30 | SESSION30_WEEKLY_LEARNING_DIGEST_AND_THESIS_REVIEW.md | Weekly digest and thesis review |
| 31 | SESSION31_STRATEGY_BACKTESTING_CHAMPION_CHALLENGER.md | Strategy backtesting |
| 32 | SESSION32_UNIFIED_SELF_IMPROVEMENT_COMMAND_CENTER.md | Unified command center |
| 33 | SESSION33_RISK_REGIME_STRATEGY_ROTATION.md | Risk regime detection |
| 34 | SESSION34_PIPELINE_CONTROLLER_LIVE_RUN_AND_OPERATIONAL_READINESS.md | Pipeline live run |
| 35 | SESSION35_PHASE1_CRON_MIGRATION_OBSERVABILITY.md | Phase 1 cron migration |

## Major Docs

| Doc | Purpose |
|-----|---------|
| MASTER_SYSTEM_DOCUMENTATION.md | Full system reference |
| ARCHITECTURE_OVERVIEW.md | Architecture and component diagram |
| ARCHITECTURE_INFOGRAM.md | Visual architecture summary |
| CHEAT_SHEET.md | Quick reference and commands |
| COST_MODEL.md | Infrastructure cost estimates |
| RESTORE_GUIDE.md | Disaster recovery |

## Audit/Reference Docs

- CONFIG_FILE_DB_MIGRATION_AUDIT.md — Config file audit
- EXECUTION_TIME_REVALIDATION_AUDIT_20260509.md — Execution path audit
- SESSION28_LEARNING_LOOP_AUDIT_20260509.md — Learning audit
- SESSION29_AGENT_CALIBRATION_AUDIT_20260509.md — Agent calibration audit
- agents_bible.md — Agent roles and capabilities
- TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md — Strategy playbook

## Archive

`docs/_archive/post_session35_cleanup_20260509/` — Superseded docs with manifest

## Safety Status

- **PAPER MODE ACTIVE — BLOCKED**
- Phase 1 cron migration installed (observability only)
- Rollback: `crontab crontab_session35_phase1_rollback.txt`
