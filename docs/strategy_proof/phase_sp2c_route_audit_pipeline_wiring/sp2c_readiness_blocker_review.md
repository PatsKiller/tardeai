# SP-2C Readiness Blocker Review

## Active Blockers (from PP-UX-2 + SP-2B)

| Blocker | Gate | Added By | Behavior |
|---------|------|----------|----------|
| route_audit_missing | route_audit | SP-2B | Flagged when trust_audit.strategy_fit.missing_route_audit=true |
| invalid_strategy_id | invalid_strategy | SP-2B | Flagged when strategy_id not in YAML configs |
| quote display-only | quote_trust | PP-UX-2 | Flagged when Finviz/yfinance is quote source |
| execution not checked | execution | PP-UX-1 | Flagged when no execution_readiness record |

## SP-2C Impact

With route audit now wired into the creation pipeline:
- **New proposals** will have route audit at creation → `route_audit_missing` blocker will NOT fire
- **Historical proposals** (SP-2B backfilled) already have route audit → blocker cleared
- **Only 2 proposals** (OSS, no scan data) still have missing route audit

The `invalid_strategy_id` blocker still applies to proposals with `strategy_id='screener'`.
SP-2C does not auto-fix these — they require operator rebuild or expiry.
