# SCREENER-ARCH-3B — Importer Membership Backfill

**Status:** PARTIAL (7/13 done, 6 deferred)

## What Was Delivered

- **Backfill**: 1,941 symbols from 2,951 scan pairs across 14 days
- **Membership**: 1,941 rows in screener_symbol_membership (all status=present)
- **History**: 1,941 entered events in membership_history
- **Reports**: Catalog (5,071 classified, 5,242 watchlist) + membership (1,941 present)

## What Is Deferred

- Per-page/raw-row persistence (current importer is single CSV, no pages)
- Dropped/stale detection (needs multi-run comparison in importer)
- Reentered detection (needs prior state comparison)
- Incubator falloff apply (needs dropped detection)
- API/dashboard endpoints

## Tests

11/11 + ARCH-3 12/12 + ARCH-2B 7/7 regression.
