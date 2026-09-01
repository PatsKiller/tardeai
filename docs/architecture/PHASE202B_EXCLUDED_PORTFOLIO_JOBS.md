# Phase 202B — Excluded Portfolio-Maintenance Jobs

Status:      HISTORICAL
as_of:       2026-06-05T10:59:04-04:00
Measured at: efcc51365 / not measured

Jobs deliberately **NOT migrated** in the P0-safe pilot. They remain on their existing legacy
schedules, untouched. Rendered as echo-only `EXCLUDED_NOT_RUN` in the controller for visibility.

| Job | Reason excluded | Future gate needed |
|-----|-----------------|--------------------|
| `run_price_cache.sh` (`portfolio-price-cache.timer`) | **Writes the price cache that feeds trading/proposal/eligibility decisions.** Per phase rule, cache rebuilds that mutate production DB / feed trading are design/diff-only, not migrated. | A dedicated pilot with a **price-cache row diff** (controller cache rows == legacy cache rows) proving identical output before apply; classify P1-careful. |
| `db_retention.py` (cron) | **Destructive** — 14 DB DELETE/retention operations. Migrating a destructive job is explicitly prohibited this phase. | A separate approval with a **deletion-set dry-run diff** (controller would-delete set == legacy would-delete set, count + keys) before any apply; runs dry-run-count-only until proven identical. |

## Hard rule honored
**No destructive job and no production-DB-mutating cache job is migrated or applied in Phase 202.**
Both are inventoried and diff-planned only.

## Controller treatment
The hardened controller lists these two as `EXCLUDED_NOT_RUN` echo lines (never executed, even with
`--apply`), so the Control Plane shows them as known-excluded rather than silently dropped.

---
*2 jobs excluded (price-cache feeds trading; db_retention destructive); both remain on legacy
schedules, untouched; future gates documented.*
