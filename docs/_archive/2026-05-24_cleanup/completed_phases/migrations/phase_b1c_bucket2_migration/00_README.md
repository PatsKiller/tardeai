# B-1C — Bucket 2 Migration and Scalp Boundary Guard

**Status:** COMPLETE (dry-run only — DB sync deferred)

## Purpose

Validates Bucket 2 (MULTI_DAY) watchpool migration and enforces boundary between
Trade AI paper proposal system and any separate daily momentum scalp workflows.

## Bucket 2 Status: OPERATIONAL

- 9 Bucket 2 strategies with MULTI_DAY freshness, all watchpool=true
- Watchpool is active: DWSN (speculative_growth) entered today 4:08 AM
- TTL ranges: 5-20 days per strategy
- Rollback API available for each strategy

## Scalp Boundary: CLEAN

- No confirmed leakage of external daily scalp records into paper proposals
- Trade AI `momentum_scalp` YAML strategy is valid (SAME_DAY, watchpool=false)
- 30 momentum_scalp proposals are from standard pipeline (auto_gen, promoter, etc.)
- 2 items flagged for review (proposed_by='system' and 'telegram_manual') — standard sources
- Boundary design documented with namespace/filtering rules

## Migration Dry-Run

- YAML: 23 strategies, DB: 24 (includes `invalid_non_security`)
- No missing strategies in DB
- No blockers
- DB sync not applied (dry-run only)

## SP-2C Re-Check

- 0 new proposals after SP-2C — awaiting promoter to fire
- Watchpool is populating (confirms pipeline active)

## Safety

- All read-only. No mutations, no strategy changes.
- Tests: 13/13, SP-2C 17/17 regression.
