# ATP-3 — Proposal Readiness Truth Layer and Action Workflow

**Status:** COMPLETE

## What Was Fixed

1. **Unknown quote counter**: `unknown_quote_count` added to summary (was hidden under stale=0)
2. **Approval gate**: Unknown quote now blocks approval (was incorrectly allowed for all 5 proposals)
3. **R:R gate**: R:R below 2.0 now blocks approval (CODX 1.91, DOC 1.99 were incorrectly approvable)
4. **Primary blockers**: Each proposal now lists exact blockers (quote_never_checked, execution_readiness_missing, rr_below_minimum, ai_review_missing, backtest_missing)
5. **High RVOL/gap warnings**: CODX flagged for RVOL 301x and gap +42%
6. **Approval override fixed**: Paper-trading approval override now requires quote check before allowing

## Before/After

| Metric | Before ATP-3 | After ATP-3 |
|--------|-------------|-------------|
| Unknown quote count | 0 (hidden) | 5 |
| Stale count | 0 | 0 |
| Approval allowed | 5 (all!) | 0 |
| Primary blockers shown | No | Yes |
| R:R < 2.0 blocks | No | Yes |

## Tests

13/13 pass.
