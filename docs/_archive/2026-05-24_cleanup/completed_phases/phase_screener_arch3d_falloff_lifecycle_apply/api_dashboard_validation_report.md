# SCREENER-ARCH-3D — API/Dashboard Validation

## API Responses (post-apply)

### /api/v2/incubator-lifecycle/summary
- active_candidates: 1,129
- source_missing: 198
- retained_by_ttl: 184
- expired: 0
- archived: 10
- reentered: 55

### /api/v2/screener-membership/summary
- total: 2,038
- present: 1,311
- dropped: 727
- lifecycle detection working: True

### /api/v2/ticker-catalog/summary
- cataloged: 1,139
- active: 1,129

## Lifecycle State Distribution (incubator_universe)

| State | Count |
|-------|-------|
| source_missing | 885 |
| active | 153 |
| needs_refresh | 89 |
| ROLLED_ON (pre-existing) | 2 |

## Dashboard

Paper Governance > Scanner Catalog Lifecycle card shows updated values.
Source-missing and dropped counts visible.
Data confidence: PARTIAL (dropped > 0 but < present).

## Validation

- No candidates deleted
- All 1,129 still status=ACTIVE
- lifecycle_state now set for all candidates
- 136 expire candidates blocked (no operator flag)
- API reflects updated state
