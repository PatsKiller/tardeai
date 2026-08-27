# Session 30: Weekly Learning Digest and Post-Trade Thesis Review

**Date:** 2026-05-09  
**Status:** Implemented, paper-only, observation phase

## Purpose

Close the operator feedback loop: summarize what the system learned, which trades worked/failed, whether theses held, which agents/sources/strategies are improving, and what John should review.

## Core Principle

The system can summarize, explain, score, and propose. It cannot silently promote, change configs, alter agent weights, or trade.

## Schema (5 tables)

- `trade_thesis_reviews` — post-trade thesis vs outcome scoring
- `weekly_learning_digests` — one digest per weekly period
- `weekly_learning_digest_items` — atomic digest items
- `thesis_learning_evidence_links` — link reviews to learning governance
- `learning_digest_delivery_log` — Telegram/delivery tracking

## Scripts

| Script | Purpose |
|--------|---------|
| `trade_thesis_review_engine.py` | Score thesis vs actual outcome for closed trades |
| `weekly_learning_digest.py` | Generate weekly digest from all subsystems |
| `weekly_learning_digest_delivery.py` | Send digest via Telegram |
| `session30_validate.py` | 22 validation tests |

## Thesis Scoring

Each closed/cancelled trade is scored on:
- thesis_score 0-100 (did the thesis hold?)
- execution_score 0-100 (entry quality)
- risk_management_score 0-100 (stop/target quality)
- agent_alignment_score 0-100 (did agents agree with outcome?)
- source_quality_score 0-100 (source reliability)
- outcome_score -100 to +100 (PnL/R result)

## Weekly Digest Sections

1. Safety status, 2. Paper trading summary, 3. Trade thesis reviews,
4. Agent calibration, 5. Source/ingestion learning, 6. Strategy learning,
7. Pending recommendations, 8. Pending config proposals,
9. Low sample warnings, 10. What to review, 11. What not to act on yet

## API Endpoints (5)

- `GET /api/v2/weekly-learning-digest`
- `GET /api/v2/weekly-learning-digest/latest`
- `GET /api/v2/weekly-learning-digest/<id>`
- `GET /api/v2/trade-thesis-reviews`
- `GET /api/v2/trade-thesis-reviews/<id>`

## Telegram Commands (5)

`weekly learning` | `weekly learning generate` | `weekly learning send` | `thesis reviews` | `thesis review run`

## Dashboard

Route: `/v2/weekly-learning`  
Tabs: Latest Digest, Thesis Reviews, Digest History

## Pipeline Stages (3)

- `post_trade_thesis_review` — daily
- `weekly_learning_digest_generate` — weekly
- `weekly_learning_digest_delivery_dry` — weekly dry-run

## Validation: 22/22 PASS

## Current State

- 3 closed trades, 4 thesis reviews (all unresolved due to missing proposal links)
- All findings are low_sample_size
- No digest delivered yet (manual send required)
- No config changes, no cron installed
