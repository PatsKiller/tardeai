# Session 35: Phase 1 Cron Migration — Safe Observability Stages

**Date:** 2026-05-09  
**Status:** Installed and validated

## What Was Migrated

3 safe observability-only stages now run via Pipeline Controller at 7:15 AM daily:
- `system_facts` — regenerate system_facts.json
- `self_improvement_snapshot` — write self-improvement snapshot to DB
- `self_improvement_component_health` — refresh component health

## What Was NOT Migrated

- All 141 existing cron jobs remain unchanged
- No broker/order stages
- No Telegram sends
- No config promotion
- No learning implementation
- No strategy changes

## Crontab Change

**Added (purely additive):**
```
# === SESSION35 PHASE1 OBSERVABILITY VIA PIPELINE CONTROLLER ===
15 7 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/pipeline_controller.py --pipeline daily --run-label cron_phase1_observability --only-stages system_facts,self_improvement_snapshot,self_improvement_component_health --allow-degraded >> logs/cron_phase1_observability.log 2>&1
# === END SESSION35 PHASE1 ===
```

**Removed/commented:** None (no existing system_facts/self_improvement cron entries existed)

## Rollback

```
crontab /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/crontab_session35_phase1_rollback.txt
```

## Backup

`backups/cron_migration/crontab_before_session35_latest.txt`

## Manual Validation Results

- Dry-run: 3 stages SUCCESS
- Live manual test: 3 stages SUCCESS, 0 failed
- Cron command manual test: 3 stages SUCCESS
- All logs created

## Phase 2 Criteria

- 3 consecutive successful cron_phase1_observability runs
- No duplicate outputs
- No safety changes
- No missed SLA
- No unexpected DB growth
- No operator confusion

## Validation: 18/18 PASS

## Safety: Paper BLOCKED, holdings $1,189,457 unchanged, rollback available
