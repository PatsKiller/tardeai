# Phase 201G — Portfolio-Maintenance Migration Risk Model

Status:      HISTORICAL
as_of:       2026-06-05T10:45:19-04:00
Measured at: efcc51365 / not measured

Classification of the 201F candidates. Design only.

## P0-safe (reports / backups / read-only — migrate first)
- `portfolio-backup` (run_pg_backup.sh) — DB backup, no mutation of live state.
- `portfolio-daily` / `portfolio-weekly` / `portfolio-monthly` — reports (read holdings, write report artifacts).
- `portfolio-lookthrough` (run_lookthrough.sh) — read-only holdings look-through analysis.
- `backup_secrets_state.sh` — encrypted offsite backup (0 broker refs).

These have no broker/API mutation and no trading writes → lowest risk, first to migrate.

## P1-careful (writes that affect dashboards / DB state — migrate after P0, extra diff)
- `portfolio-price-cache` (run_price_cache.sh) — writes the **price cache** consumed by v3 dashboards;
  uses Alpaca **paper** read API for quotes (no orders). Risk = stale/incorrect cache if it changes
  behavior; diff must verify cache rows match legacy.
- `db_retention.py` — performs **DB deletes per retention policy**; a controller change must NOT alter
  the retention window or delete anything extra. Requires a dry-run/count diff before any apply.

## P2-hold (do NOT migrate in a portfolio pilot)
- Anything that can influence proposals, alter trade state, touch a broker order path, or affect risk
  gates. **None of the 201F candidates fall here** — but the boundary is explicit so the pilot can't
  drift into trade-affecting territory. `portfolio-server` (the API service) is excluded entirely.

## Recommended pilot ordering
1. P0-safe reports + backups first (mirror the governance pattern; trivial diff).
2. P1-careful (price-cache, db_retention) only after P0 proves clean, each with a **count/row diff**
   (esp. db_retention — confirm identical deletion set in dry-run before apply).

---
*Risk model only. P0-safe set is the safe next pilot; P1 needs row-diffs; P2 boundary keeps the pilot
out of trade-affecting jobs.*
