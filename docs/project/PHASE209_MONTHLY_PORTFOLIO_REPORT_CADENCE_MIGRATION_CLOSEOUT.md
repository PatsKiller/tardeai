# Phase 209 — Monthly Portfolio Report Cadence Migration — Closeout — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T13:20:39-04:00
Measured at: efcc51365 / not measured

## Outcome
The monthly portfolio-report cadence is **migrated** into the cadence-aware controller, scheduled,
validated, and the **legacy monthly timer retired** (operator-approved). Advisory-draft aware.

## Pattern executed
preflight + classify `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY` (209A) → harden (guard wired into run_monthly)
→ dry-run PASS → parallel apply (exit 0, **841s ~14 min**, ok) → diff PASS (`compare_portfolio_daily_outputs.py
--cadence monthly`) → schedule parallel (`tradeai-portfolio-monthly-cadence.timer` day-1 07:35, legacy kept
active) → scheduled-equivalent systemd cycle PASS (Result=success, overall=ok) → **retire legacy** (approved).

## Evidence
- Apply: `portfolio_monthly_report` ok; review-only; exclusions correct; artifacts
  `data/portfolios/reports/monthly_2026-06-07.docx`+`.json`, `reports_hub.html`.
- systemd cycle: `Result=success`, `overall=ok`.
- comparator `--cadence monthly`: **PASS** (daily/weekly regression unaffected).
- Safety across both cycles: 0 paper_trades changed, 0 proposals, 0 protection advisories;
  **no strategy-YAML mutation** (0 files touched). Monthly chain includes Claude Sonnet monthly report +
  qwen3:14b narrative + Opus yaml-advisor — all **fail-soft** (model/key gated), review-only, unchanged.

## Retirement
- `systemctl --user disable --now portfolio-monthly.timer` → **inactive/disabled**; unit files preserved.
- Cadence `tradeai-portfolio-monthly-cadence.timer` (day-1 07:35) is the **sole** monthly path.
- **retired_legacy_count = 1.** Snapshot: `data/runtime/legacy_monthly_retirement_20260607/`.
  Rollback: `systemctl --user enable --now portfolio-monthly.timer`.
- Out of scope, left active: separate `run_alex_daily.py --monthly` @09:00 day-1 cron.

## Safety (held / verified)
no broker/order/proposal/protection/trading mutation · no GO/WAIT · no strategy scoring/YAML change · no
paper stops/orders · advisory drafts review-only · db_retention + price_cache + secrets-data excluded ·
lookthrough NOT migrated · backup + daily + weekly cadences unchanged · safety-net watchdog untouched ·
live trading ZERO · live endpoint blocked (paper, LLM_DISABLE_LIVE_EXECUTION) · Level 7 prohibited.

## v3 visibility
`/api/v2/system/portfolio-cadence-status`: backup/daily/weekly/**monthly = migrated** (all legacy retired);
**lookthrough = not_migrated** (only remaining report cadence). db_retention/price_cache excluded.

## Next recommended gate
**Lookthrough** cadence — the last report cadence (a READ_ONLY_SNAPSHOT, even lower-risk). After that,
all report cadences are controller-owned; db_retention / price_cache / destructive cleanup never auto-migrate.
