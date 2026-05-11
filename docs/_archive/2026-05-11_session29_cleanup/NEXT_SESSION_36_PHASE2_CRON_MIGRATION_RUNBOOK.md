# Next Session Runbook — Phase 1 Observation and Session 36 Readiness

## Purpose

This runbook is for the next session, 2–3 days after Session 35. It tells Claude Code exactly what to check before deciding whether Phase 2 cron migration is safe.

## Current Baseline

- Phase 1 cron migration is active.
- One new Pipeline Controller cron job runs daily at 7:15 AM.
- Migrated stages:
  - system_facts
  - self_improvement_snapshot
  - self_improvement_component_health
- Current facts after doc cleanup:
  - Tables: 299
  - Scripts: 354
  - Strategies: 20
  - Cron jobs: 142
  - Pipeline stages: 44
  - Holdings: $1,189,457
  - Trading: BLOCKED
- ALPACA_MODE=paper
- LIVE_TRADING absent
- holdings.json remains authoritative.
- Rollback command:
  crontab crontab_session35_phase1_rollback.txt

## Required Go / No-Go Rule

Do not start Session 36 unless Phase 1 has 3 successful scheduled cron runs.

A successful scheduled run means:

- cron_phase1_observability.log shows a scheduled 7:15 AM run.
- Pipeline Controller created a run record.
- Only Phase 1 observability stages ran.
- No broker/order stage ran.
- No Telegram send ran.
- No config/promotion stage ran.
- No active strategy/source/screener/execution/agent config changed.
- system_facts regenerated correctly.
- self-improvement snapshot/component health updated correctly.
- holdings guard passed.
- paper gate remained BLOCKED.
- no duplicate/conflicting outputs.
- no unexpected DB growth.
- no SLA miss.
- no operator confusion.

## Prompt 1 — Phase 1 Observation Review

Paste this into Claude Code first, 2–3 days from now:

```text
You are Claude Code working on Trade AI v12.

Objective:
Review Phase 1 cron migration after 2–3 days of scheduled runs and decide whether Session 36 can proceed.

Do not change code.
Do not change SQL.
Do not change crontab.
Do not change .env.
Do not modify holdings.json.
Do not enable live trading.
Do not execute broker orders.
Do not send Telegram.
Do not modify active configs.

Project root:
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

Current expected baseline:
- Phase 1 cron migration active.
- 7:15 AM daily Pipeline Controller cron entry.
- Safe stages only:
  - system_facts
  - self_improvement_snapshot
  - self_improvement_component_health
- Rollback available:
  crontab crontab_session35_phase1_rollback.txt

STEP 1 — Safety checks

cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; assert v>1_000_000, 'WIPED'; print(f'Holdings OK: ${v:,.0f}')"

.venv/bin/python scripts/live_trading_gate.py --status --json
.venv/bin/python scripts/live_trading_gate.py --assert-safe

grep '^ALPACA_MODE=' .env || true
grep '^LIVE_TRADING=' .env || true

STEP 2 — Inspect cron log

tail -300 logs/cron_phase1_observability.log

Determine:
- number of scheduled runs since Session 35,
- number of successful runs,
- any failures,
- any skipped stages,
- any unsafe stages,
- any SLA misses,
- whether outputs updated.

STEP 3 — Inspect pipeline runs

Use DB/API/CLI as appropriate:

.venv/bin/python scripts/pipeline_controller.py --pipeline daily --list-stages

curl -s http://localhost:7777/api/v2/pipeline-controller/runs | python3 -m json.tool
curl -s http://localhost:7777/api/v2/pipeline-controller/status | python3 -m json.tool
curl -s http://localhost:7777/api/v2/pipeline-controller/failures | python3 -m json.tool

Confirm the scheduled cron runs exist and show only the allowed Phase 1 stages.

STEP 4 — Inspect self-improvement status

curl -s http://localhost:7777/api/v2/self-improvement/status | python3 -m json.tool
curl -s http://localhost:7777/api/v2/self-improvement/component-health | python3 -m json.tool
curl -s http://localhost:7777/api/v2/system-facts | python3 -m json.tool

STEP 5 — Check for unsafe behavior

Search logs for risky terms:

grep -iE "alpaca|submit_order|place_order|execute-ready|broker order|cancel_order|replace_order|close_position|telegram send|approve implementation|promote challenger" logs/cron_phase1_observability.log || true

Expected:
- no unsafe hits from the Session35 cron block.

STEP 6 — Generate facts

.venv/bin/python scripts/generate_system_facts.py

STEP 7 — Produce go/no-go report

Create:

docs/project/SESSION36_GO_NO_GO_PHASE1_OBSERVATION_YYYYMMDD.md

Replace YYYYMMDD with actual date.

Include:
1. Scheduled Phase 1 run count.
2. Successful scheduled run count.
3. Failed run count.
4. Pipeline run IDs.
5. Stages executed.
6. Stages skipped/blocked.
7. Unsafe search result.
8. system_facts status.
9. self-improvement status.
10. holdings guard status.
11. paper gate status.
12. whether 3 clean scheduled runs exist.
13. GO or NO-GO for Session 36.
14. If NO-GO, state whether rollback is recommended.

Final answer:
- GO if 3 clean scheduled runs.
- NO-GO if fewer than 3 clean scheduled runs or any unsafe behavior.
```

## Prompt 2 — Session 36 (only if GO)

If the observation review returns GO, paste this into Claude Code:

```text
You are Claude Code working on Trade AI v12.

SESSION 36 OBJECTIVE:
Perform Phase 2 cron migration for low-risk analysis and regime stages.

Phase 1 observation confirmed 3+ successful scheduled runs. Proceed with Phase 2.

Phase 2 scope:
- market_regime_snapshot
- strategy_rotation_signal_refresh
- learning_governance_status
- ingestion_learning_analysis
- trade_learning_analysis
- champion_challenger_summary
- agent_recommendation_normalization
- agent_outcome_linking

Do NOT migrate:
- broker/order stages
- Telegram sends
- config promotion
- learning implementation
- challenger promotion
- active strategy/source/screener changes

Follow the same Phase 1 pattern:
1. Backup crontab.
2. Create proposed + rollback files.
3. Manual dry-run.
4. Manual live validation.
5. Safety review.
6. Install only if safe.
7. Manual cron-command test.
8. Document observation plan.
9. Validate.
10. Commit.

Project root:
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

## Rollback Reference

If at any point Phase 1 cron migration needs to be undone:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
crontab crontab_session35_phase1_rollback.txt
crontab -l | grep -n "SESSION35" || echo "Session35 block removed"
```
