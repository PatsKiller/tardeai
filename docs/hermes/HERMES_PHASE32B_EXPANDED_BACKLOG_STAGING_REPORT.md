# Hermes Phase 32B — Expanded Backlog Staging Report

**Date:** 2026-06-01
**Status:** COMPLETE — 5 rows staged

## Inserted Rows

| ID | Source Surface | Title | Priority |
|----|---------------|-------|----------|
| 24 | journal | Journal learning system empty | medium |
| 25 | backtest | momentum_scalp 30% win rate (n=20) | high |
| 26 | backtest | all_signals 33.9% win rate (n=59, pf=0.6099) | high |
| 27 | backtest | Insufficient backtest samples (4 strategies, n≤2) | low |
| 28 | catalyst | Generic catalyst classification gap (25+ 'other' events) | medium |

## Post-Staging State

| Metric | Before | After |
|--------|--------|-------|
| Total rows | 23 | 28 |
| Promoted | 10 | 10 (unchanged) |
| Staged | 13 | 18 |
| research_backlog type | 5 | 10 |
| Embeddings | 7 | 7 (unchanged) |
| Cache sections | 10 | 10 (unchanged) |

## Safety

- [x] 5 rows inserted (under 10 cap)
- [x] All status='staged'
- [x] All research_type='research_backlog'
- [x] All advisory_only=true, not_execution=true, operator_review_required=true
- [x] No production writes
- [x] No embeddings
- [x] No promotions
- [x] Rollback SQL ready

## Rollback

```bash
PGPASSWORD='...' psql -h localhost -U trade_ai -d trade_ai -f docs/hermes/HERMES_PHASE32B_EXPANDED_BACKLOG_STAGING_ROLLBACK.sql
```
