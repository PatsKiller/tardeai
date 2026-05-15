# Phase 5 — Feedback and Learning Loop

**Status:** COMPLETE — human-review-only feedback pipeline operational

## Purpose

Safe feedback/learning loop that collects observations, scores model usefulness, and generates human-reviewable recommendations without auto-applying changes.

## Commands

```bash
# Collect observations
.venv/bin/python scripts/collect_phase5_feedback_observations.py --since-days 30 --apply --verbose

# Generate recommendations
.venv/bin/python scripts/generate_phase5_learning_recommendations.py --since-days 30 --apply --verbose

# Review queue
.venv/bin/python scripts/report_phase5_human_review_queue.py --verbose

# Rollback
./scripts/rollback_phase5_feedback_learning.sh --status
```

## Tables

- `llm_feedback_observations` — model output observations
- `llm_learning_recommendations` — pending human-review recommendations
- `llm_prompt_experiments` — prompt experiment drafts

## Safety

- All recommendations start as `pending_human_review`
- No auto-applied prompt/routing/trading changes
- No .env, cron, broker, or execution changes
- Read-only collection from existing tables
