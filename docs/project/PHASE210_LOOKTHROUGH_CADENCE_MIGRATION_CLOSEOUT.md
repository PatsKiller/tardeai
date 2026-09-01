# Phase 210 — Lookthrough Cadence Migration — Closeout — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T16:58:08-04:00
Measured at: efcc51365 / not measured

## Outcome
The lookthrough cadence (the **last** report-family cadence) is **migrated**, scheduled, validated, and the
**legacy lookthrough timer retired** (operator-approved). **All portfolio report cadences are now
controller-owned.**

## Pattern executed
preflight + classify `READ_ONLY_SNAPSHOT` (210A) → harden (guard wired into run_lookthrough; comparator
generalized for the READ_ONLY_SNAPSHOT label) → dry-run PASS → parallel apply (exit 0, 3s, ok) → diff PASS
(`compare_portfolio_daily_outputs.py --cadence lookthrough`) → schedule parallel
(`tradeai-portfolio-lookthrough-cadence.timer` 1st-Sun 06:30, legacy kept active) → scheduled-equivalent
systemd cycle PASS (Result=success, overall=ok) → **retire legacy** (operator-approved).

## Evidence
- Apply: `portfolio_lookthrough` ok; READ_ONLY_SNAPSHOT; price_cache + db_retention excluded.
- systemd cycle: `Result=success`, `ExecMainStatus=0`, `overall=ok`.
- comparator `--cadence lookthrough`: **PASS**.
- Safety: 0 paper_trades changed, 0 proposals; no advisory drafts created (read-only); no broker/order/
  protection/strategy mutation.

## Retirement
- `systemctl --user disable --now portfolio-lookthrough.timer` → **inactive/disabled**; unit files preserved.
- Cadence `tradeai-portfolio-lookthrough-cadence.timer` (`OnCalendar=Sun *-*-01..07 06:30:00` = 1st Sunday
  monthly) is the **sole** lookthrough path.
- **retired_legacy_count = 1.** Snapshot: `data/runtime/legacy_lookthrough_retirement_20260607/`.
  Rollback: `systemctl --user enable --now portfolio-lookthrough.timer`.

## Portfolio-maintenance cadence migration — COMPLETE
`/api/v2/system/portfolio-cadence-status` → `all_report_cadences_migrated: true`:

| Cadence | Status | Legacy timer | Cadence timer |
|---|---|---|---|
| backup | migrated | retired | 02:30 daily |
| daily | migrated | retired | Mon-Fri 07:30 |
| weekly | migrated | retired | Sun 20:30 |
| monthly | migrated | retired | day-1 07:35 |
| **lookthrough** | **migrated** | **retired** | 1st-Sun 06:30 |
| db_retention / price_cache | **excluded** (never auto-migrate) | — | — |

## Safety (held / verified)
no broker/order/proposal/protection/trading mutation · no GO/WAIT · no strategy scoring/YAML change · no
paper stops/orders · advisory drafts review-only (none for lookthrough) · db_retention + price_cache +
secrets-data excluded · safety-net watchdog untouched · live trading ZERO · live endpoint blocked · Level 7
prohibited.

## Next recommended gate
None required for report cadences — all controller-owned. Remaining (out of scope, prohibited from
auto-migration): `db_retention` (destructive DB deletes) and `price_cache` (feeds trading/proposal) — both
remain `EXCLUDED_NOT_RUN`, each a future deletion-set/diff gate only if ever explicitly authorized.
