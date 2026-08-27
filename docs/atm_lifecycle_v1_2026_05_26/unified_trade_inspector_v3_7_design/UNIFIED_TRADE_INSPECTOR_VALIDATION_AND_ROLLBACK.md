# Validation and Rollback

## Tests
- Inspector API returns aggregated data for BLMN, APPS, AGNC
- BLMN #37 shows as duplicate_submit_race
- BLMN #38 shows as real open
- APPS shows repair audit trail
- No writes verified
- UI renders all tabs

## Rollback
git revert HEAD
# No schema to rollback — v3.7 is read-only API + UI
