# Hermes Phase 15 — Capped Promotion Execution Report

**Date:** 2026-05-31
**Status:** COMPLETE

## Summary

Promoted 3 operator-reviewed candidates from `hermes_research_intelligence` (staged) to `llm_intelligence_cache` as advisory-only intelligence.

## Candidates Promoted

| ID | Symbol | Research Type | Confidence | Finding |
|----|--------|---------------|------------|---------|
| 8 | FJSCX | ticker_thesis_challenge | 0.6 | Inconsistent trading strategy, missing entry/exit criteria and exit reasoning |
| 10 | APAM | ticker_thesis_challenge | 0.6 | Downtrend, Strong Sell, all 5 trades lost — high risk |
| 11 | TRX | ticker_thesis_challenge | 0.6 | Data integrity concerns — analyst rec incongruent with Strong Sell, zero-value entries |

## Cache Sections Created

- `hermes_ticker_thesis_challenge_FJSCX`
- `hermes_ticker_thesis_challenge_APAM`
- `hermes_ticker_thesis_challenge_TRX`

## Post-Promotion State

| Metric | Before | After |
|--------|--------|-------|
| hermes_research_intelligence rows | 11 | 11 |
| Promoted | 7 | 10 |
| Staged | 4 | 1 (TELO) |
| llm_intelligence_cache hermes sections | 7 | 10 |
| hermes_promotion_audit records | 7 | 10 |

## Safety Verification

- [x] Only approved symbols promoted (FJSCX, APAM, TRX)
- [x] Exactly 3 rows promoted (not more)
- [x] No broker mutations
- [x] No production table mutations (only llm_intelligence_cache + hermes_* staging)
- [x] All rows tagged advisory_only in metadata
- [x] Audit trail recorded with rollback SQL per row
- [x] Dashboard API reflects updated counts
- [x] Rollback SQL created: `sql/migrations/20260531_hermes_phase15_promote_3_candidates_rollback.sql`

## Rollback

```bash
PGPASSWORD='...' psql -h localhost -U trade_ai -d trade_ai -f sql/migrations/20260531_hermes_phase15_promote_3_candidates_rollback.sql
```
