# SCREENER-ARCH-3D — Operator Approval Gate

## Dry-Run Totals

| State | Count |
|-------|-------|
| Active (keep) | 153 |
| Source missing / retained by TTL | 751 |
| Expired pending review | 136 |
| Needs refresh (no data) | 89 |
| Protected (watchpool) | 15 |

## Safe Apply (no flag needed)

993 candidates will get lifecycle_state updated:
- 153 -> active
- 751 -> source_missing
- 89 -> needs_refresh

This is non-destructive. No status change to EXPIRED. No deletion.

## Expire Apply (requires --operator-approved-expire)

136 candidates would be marked EXPIRED + expired_pending_operator_review.
15 are protected by active watchpool and will NOT be expired.
Net: ~121 would actually expire.

**No expire/archive apply may run unless `--operator-approved-expire` or `--operator-approved-archive` is passed.**

## Apply Commands

Safe apply (recommended):
```bash
.venv/bin/python scripts/report_and_apply_incubator_falloff_lifecycle.py \
  --since-days 14 --apply --verbose
```

Expire apply (only if operator approves):
```bash
.venv/bin/python scripts/report_and_apply_incubator_falloff_lifecycle.py \
  --since-days 14 --apply --operator-approved-expire --verbose
```

## Rollback

If safe apply needs reversal:
```sql
UPDATE incubator_universe SET lifecycle_state = NULL WHERE lifecycle_state IN ('source_missing','needs_refresh');
```

This is non-destructive — lifecycle_state is informational, status remains ACTIVE.
