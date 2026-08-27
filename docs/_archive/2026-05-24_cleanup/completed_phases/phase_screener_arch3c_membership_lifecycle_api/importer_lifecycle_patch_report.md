# SCREENER-ARCH-3C — Importer Lifecycle Patch Report

## What Was Built

`scripts/backfill_screener_membership_transitions.py` implements prior-vs-current membership comparison with:

1. **`load_prior_memberships()`** — Loads current membership snapshot per screener
2. **`build_daily_symbol_sets()`** — Merges all intraday time slots into one daily set per source
3. **`classify_transitions()`** — Compares prior vs current, classifies entered/present/dropped/stale/expired/reentered
4. **`apply_transition()`** — Writes history event + updates membership record (idempotent by run_id+event_type)
5. **`event_exists()`** — Idempotent guard prevents duplicate history events on rerun

## Mass-Drop Protection

Triggered when >50% of prior members are missing from a run with <50% of prior count:
- 8 runs triggered protection (May 6-15, pre-SCREENER-ARCH-2 full ingestion era)
- Additions (entered/reentered/present) processed normally
- Drops suppressed to avoid false mass-drop from partial coverage

## Run Sequencing

- Runs ordered by `(source, scanned_at::date)` — one comparison per source per day
- All time slots (0400, 0900, etc.) merged into single daily symbol set
- Prior state updated after each day for correct cascading (dropped -> stale -> expired)

## Thresholds

| Threshold | Value |
|-----------|-------|
| STALE_THRESHOLD | 3 consecutive missing runs |
| EXPIRE_THRESHOLD | 7 consecutive missing runs |
| MASS_DROP_PCT | 50% |

## No Deletions

- Expired symbols are marked, never removed from membership table
- History is append-only
- Catalog rows never deleted
