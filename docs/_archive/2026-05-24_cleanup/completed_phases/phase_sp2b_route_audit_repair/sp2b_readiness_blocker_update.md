# SP-2B Readiness Blocker Update

## New Blockers Added

| Gate | Condition | Reason | Action |
|------|-----------|--------|--------|
| `route_audit` | strategy_fit.missing_route_audit = true | Strategy assignment unverified | Run route audit backfill or wait for SP-2C |
| `invalid_strategy` | strategy_id not in YAML configs | Not a valid YAML strategy | Rebuild proposal with valid strategy |

## Behavior

- Blockers are added to `approval_blockers` array per proposal
- Blockers appear in PP-UX-1 decision banner and PP-UX-2 trust audit panel
- Blockers do NOT remove existing approval capability for paper-learning tests
- Blockers are informational for the operator — approval confirm modal still available
- No execution logic changed

## Impact

- 74/83 proposals will show "Route audit missing" blocker
- 6/83 proposals will show "Invalid strategy" blocker (strategy_id='screener')
- Operator can still approve via cautious paper-test confirm modal
