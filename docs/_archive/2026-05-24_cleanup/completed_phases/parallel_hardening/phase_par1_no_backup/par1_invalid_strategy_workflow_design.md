# PAR-1 Invalid Strategy Proposal Workflow Design

## Problem

6 proposals have strategy_id='screener' — not a valid YAML strategy.
These should not be decision-ready.

## Why Invalid

- No YAML config exists for 'screener'
- No entry criteria, risk rules, or exit rules defined
- Route audit backfill shows router suggests different strategies
- These came from early pipeline runs before strategy assignment was enforced

## Operator Choices

1. **Expire** — Mark as expired/rejected. Safest option.
2. **Rebuild** — Create new proposal with router's suggested strategy. Requires operator review.
3. **Leave for review** — Keep as-is with invalid_strategy blocker visible.

## Why No Automatic Reassignment

- Changing strategy_id after creation would invalidate existing audit trail
- Route audit shows mismatches — but router may not be more correct
- Operator must decide which strategy fits the specific trade thesis

## Current Blockers

SP-2B added `invalid_strategy` blocker to API trust_audit. These 6 proposals
show "strategy_id='screener' is not a valid YAML strategy" in the approval
blockers. Operator can still see them but cannot approve without confirm override.

## Affected Proposals

FLYW (id=74), OSS (id=56), KVHI (id=27), BLMN (id=24), EVC (id=22), NNE (id=21)

## Future PP-UX-3

A future phase could add an "Expire Invalid" or "Rebuild with Strategy" button
to the Paper Proposals page for these specific proposals.
