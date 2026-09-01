# Phase 201H — Portfolio-Maintenance Migration Plan (no runtime change)

Status:      HISTORICAL
as_of:       2026-06-05T10:45:19-04:00
Measured at: efcc51365 / not measured

Plan only. Same proven pattern as governance (Phase 200). **Not executed in Phase 201.**

## Pattern (per the governance pilot)
1. **Harden** `scripts/pipelines/run_portfolio_maintenance_pipeline.sh` into a real executor
   (currently a 199E dry-run skeleton): DRY_RUN default, safety asserts (live-off, Level-7,
   no-broker), lock, per-step logging, non-cascading, summary JSON
   `data/runtime/portfolio_maintenance_last_run.json`.
2. **Dry-run** validate (`bash -n` + DRY_RUN run; all steps listed; no broker/trade step).
3. **Parallel apply** one cycle (legacy timers/cron intact); capture summary + logs.
4. **Output diff** — `compare_portfolio_maintenance_outputs.py`: backups present, report files match
   (modulo timestamp), price-cache rows match, **db_retention deletion set identical** (count diff —
   the critical one).
5. **Schedule** the controller (systemd user timer) at the SAME cadences (Sat backup, Mon daily, Sun
   weekly/lookthrough/price-cache, monthly).
6. **Observe** one automatic cycle.
7. **Retire** legacy only after pass: disable the redundant portfolio-* timers (reversible
   `enable --now`); comment `backup_secrets_state.sh` cron with a `PHASE20x_MIGRATED` marker.

## Sequencing (from 201G)
- Migrate **P0-safe** first (backup, daily/weekly/monthly reports, lookthrough, secrets backup).
- Migrate **P1-careful** (price-cache, db_retention) only after P0 is clean, each with a row/count diff;
  db_retention runs dry-run-count-only until the deletion set is proven identical.
- **Never** include P2 / trade-affecting jobs; `portfolio-server` stays a standalone service.

## Hard constraints (carry forward)
- No live trading / live endpoint / Level 7. No holdings/order/stop mutation. No GO-WAIT or strategy
  change. Safety net (freshness monitor + watchdog) untouched. v3 canonical; no v2 UI.

## Approval
This plan is **design-only**; executing it requires a separate explicit operator approval (a future
Phase 202-style prompt), exactly as Phase 200 required for governance.

---
*Plan only. Mirrors governance pilot; P0-safe first; db_retention needs a deletion-set diff before apply.*
