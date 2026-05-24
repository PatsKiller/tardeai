# SP-2B — Route Audit Backfill and Strategy Assignment Repair

**Status:** COMPLETE (dry-run only — backfill apply deferred to operator)

## Root Cause

Neither `auto_proposal_generator.py` nor `incubator_proposal_promoter.py` calls
`multi_setup_router.store_setup_matches()` during proposal creation. The function
exists but is only available in manual `--pending-proposals` mode.

## Scripts Created

- `scripts/report_route_audit_root_cause.py` — Documents the gap
- `scripts/backfill_proposal_route_audit.py` — Backfill tool (default: dry-run)
- `scripts/report_invalid_strategy_assignments.py` — Finds non-YAML strategy_id
- `scripts/report_strategy_config_drift.py` — YAML vs DB hash comparison

## Key Findings

| Finding | Count |
|---------|-------|
| Proposals missing route audit | 74/83 (89%) |
| Backfill mismatches (router disagrees with assignment) | 46/72 (64%) |
| Invalid strategy_id='screener' | 6 |
| YAML/DB config drift | 3 (gap_and_go, momentum_scalp, swing_breakout) |

## API Blockers Added

- `route_audit` — "Route audit missing — strategy assignment unverified"
- `invalid_strategy` — "strategy_id='X' is not a valid YAML strategy"

## What Was NOT Done

- Backfill --apply was NOT run (operator must approve)
- Proposal strategy_id was NOT changed
- Strategy activation was NOT changed
- YAML configs were NOT changed

## Recommended Next

- **SP-2C**: Wire store_setup_matches into auto_proposal_generator and incubator_proposal_promoter
- **Operator decision**: Run backfill --apply to populate route audit for existing proposals
- **Operator decision**: Review 46 mismatches where router disagrees with original assignment
