# Session 36: Phase 2 Cron Migration — Analysis and Observability Stages

**Date:** 2026-05-09  
**Status:** Installed and validated

## Phase 1 GO Evidence

3 successful Phase 1 pipeline runs (dry, manual live, cron command test), all with status=success, 3 stages each, 0 failures.

## What Was Migrated (Phase 2)

15 safe analysis/observability stages now run via Pipeline Controller at 7:45 AM weekdays:

1. market_regime_snapshot
2. strategy_rotation_signal_refresh
3. learning_governance_status
4. ingestion_learning_analysis
5. trade_learning_analysis
6. champion_challenger_summary
7. agent_recommendation_normalization
8. agent_outcome_linking
9. agent_calibration_scoring
10. agent_disagreement_scoring
11. post_trade_thesis_review
12. weekly_learning_digest_generate
13. weekly_learning_digest_delivery_dry
14. backtest_dataset_build
15. strategy_backtest_smoke

## What Remains Blocked

- All broker/order stages
- All Telegram live sends
- Config promotion/implementation
- Challenger promotion
- Active strategy/source/screener changes
- Finviz production ingestion
- Candidate discovery apply

## Crontab Change

**Added (purely additive):**
```
# === SESSION36 PHASE2 ANALYSIS VIA PIPELINE CONTROLLER ===
45 7 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/pipeline_controller.py --pipeline daily --run-label cron_phase2_observability --only-stages [15 stages] --allow-degraded >> logs/cron_phase2_observability.log 2>&1
# === END SESSION36 PHASE2 ===
```

## Rollback

```
crontab /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/crontab_session36_phase2_rollback.txt
```

## Validation Results

- Dry-run: 15/15 SUCCESS
- Manual live: 15/15 SUCCESS
- Cron command test: 15/15 SUCCESS
- Validation script: 16/16 PASS
- Cron count: 142 → 143

## Observation Plan

- Check `logs/cron_phase2_observability.log` daily
- Check `/v2/pipeline-controller` for Phase 2 runs
- 3 successful scheduled runs required before Phase 3
- Phase 3 candidates: Finviz ingestion, paper analytics

## Safety

Paper BLOCKED, holdings $1,189,457 unchanged, no broker/Telegram/config/promotion
