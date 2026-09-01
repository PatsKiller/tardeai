Status:      ACTIVE
as_of:       2026-09-01T12:30:00-04:00
Measured at: CURRENT a5fc7b378 (BUILD_SHA) · origin/main dcb7ec42e · $PROJ dcb7ec42e
Canonical repo path: docs/ops/CIO_BANNER_DATA_ASOF_2026-09-01.md
Authority:   dated record of the PORTFOLIO chip freshness binding
See also:    docs/audits/CIO_SURFACE_ASOF_2026-09-01.md · AGENTS.md §9.1

# PORTFOLIO chip — freshness is `data_as_of`, not the loader run

## The defect, measured before the edit

`[VERIFIED]` The chip was bound to `overview.as_of`:

```
apps/command-center-v3/src/components/MetricStrip.tsx:37   overviewSurfaceFreshness(overview)
apps/command-center-v3/src/components/MetricStrip.tsx:85   label: 'PORTFOLIO'
apps/command-center-v3/src/lib/surfaceFreshness.ts:167     stamps = [ overview.as_of,
                                                                      pricing.last_repriced ]
built bundle:  data_as_of  0 occurrences   ·   as_of  25 occurrences
```

`as_of` is written by `portfolio_loader` as `= today`. **It records when the loader ran, not when
any data was fetched.** Live values at the time of measurement:

| field | value | what it dates |
|---|---|---|
| `as_of` | 2026-08-29 | the loader run |
| `data_as_of` | 2026-08-03 | the oldest contributing row |
| `data_as_of_account` | `moomoo_taxable_live` | which account owns it |
| `last_repriced` | 2026-09-01 12:00 ET | prices |

The chip read **3.4d**. The Schwab rows were from 08-31 (one day old) and the moomoo/alpaca CASH
rows from 08-03/04 (29 days). So `as_of` was **older than 28 of 30 rows and newer than the other
2 — wrong in both directions at once**, and described nothing in the payload.

## Two changes, because the API did not expose the field either

`[VERIFIED]` before the edit: `/api/v2/overview` returned `data_as_of: ABSENT`.

1. **`scripts/api_v2.py`** — `overview()` now emits `data_as_of` and `data_as_of_account`
   alongside `as_of`. **`as_of` is unchanged and still published**, so nothing downstream shifts
   meaning underneath it; it simply stops being the freshness clock.
2. **`surfaceFreshness.ts`** — `overviewSurfaceFreshness` keys on the data clock, reports the
   account, and **fails closed when the clock is missing**.

## The contract

```
data_as_of present      →  age = now − data_as_of ; label names the account
data_as_of absent       →  STALE · data UNDATED   ; ageHours null, dataAsOf null
```

**A missing clock is UNDATED, never "today".** A freshness field that falls back to a loader-run
date reports fresh while the data underneath is a month old — the defect this replaces. Failing
closed means a producer that stops emitting `data_as_of` is visible immediately rather than
silently flattering itself.

## Validation

```
$ npx tsc --noEmit          exit 0
$ node src/lib/surfaceFreshness.test.ts
  surfaceFreshness: 29 passed, 0 failed
```

**Mutation-verified.** Repointing the binding at `as_of` — the exact pre-fix shape — turns the
suite red on the two load-bearing assertions, and restoring returns it to green:

```
MUTATION (dataStamp = parseTimestamp(overview.as_of, nowMs)):
  [FAIL] age is dated from data_as_of, not as_of
  [FAIL] mutation: as_of would under-report the age by weeks
  27 passed, 2 failed
RESTORED:
  29 passed, 0 failed
```

A test that only agrees with the fix proves nothing; this one demonstrably detects the defect.

## What this does NOT do

- **No dollar amount changes.** Only the freshness clock and its label.
- **Moomoo was not refreshed and no cash was invented.** The chip will now report ~29 days,
  because that is how old the data is. Making the number worse is the point: 28 fresh rows were
  hiding one stale one.
- **The banner will keep reporting stale until the moomoo/alpaca cash rows actually refresh.**
  That is a broker-feed issue, not a display issue, and it remains open.

## Deployment note

The SPA reads the field from the API, and **the built bundle contains `data_as_of` 0 times before
this change** — so the served page cannot show it without a release. `prepare` rebuilds the
frontend, so a promote is required for the chip to change; the API half alone is not sufficient.
