# Phase 208 — Weekly Portfolio Report Cadence Migration — Closeout — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T11:33:49-04:00
Measured at: efcc51365 / not measured

## Outcome
The weekly portfolio-report cadence is **migrated** into the cadence-aware controller, scheduled, validated,
and the **legacy weekly timer retired** (operator-approved). Advisory-draft aware throughout.

## Pattern executed
preflight + classify `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY` (208A) → harden (guard wired into run_weekly)
→ dry-run PASS → parallel apply (exit 0, 269s, ok) → output diff PASS (comparator generalized `--cadence`)
→ schedule parallel (`tradeai-portfolio-weekly-cadence.timer` Sun 20:30, legacy kept active) →
scheduled-equivalent systemd cycle PASS (Result=success, overall=ok) → **retire legacy** (operator-approved).

## Evidence
- Apply: `portfolio_weekly_report` ok; review-only; price_cache + db_retention excluded; weekly artifacts
  produced (`portfolio_dashboard_2026-06-07_weekly.html`, `portfolio_brief_2026-06-07_weekly.docx`).
- systemd cycle: `Result=success`, `overall=ok`.
- comparator `--cadence weekly`: **PASS** (daily regression still PASS).
- Safety across both cycles: 0 paper_trades changed, 0 proposals, 0 protection advisories;
  **no strategy-YAML mutation** (yaml advisor writes review JSON only).

## Retirement
- `systemctl --user disable --now portfolio-weekly.timer` → **inactive/disabled**; unit files preserved.
- Cadence `tradeai-portfolio-weekly-cadence.timer` (Sun 20:30) is the **sole** weekly path.
- **retired_legacy_count = 1.** Snapshot: `data/runtime/legacy_weekly_retirement_20260607/`.
  Rollback: `systemctl --user enable --now portfolio-weekly.timer`.
- Out of scope, left active: separate `run_alex_daily.py --weekly` @08:00 Sun cron.

## Safety (held / verified)
no broker/order/proposal/protection/trading mutation · no GO/WAIT · no strategy scoring/YAML change · no
paper stops/orders · advisory drafts review-only · db_retention + price_cache + secrets-data excluded ·
monthly/lookthrough NOT migrated · backup + daily cadences unchanged · safety-net watchdog untouched ·
live trading ZERO · live endpoint blocked (paper, LLM_DISABLE_LIVE_EXECUTION) · Level 7 prohibited ·
qwen3:14b narrative fails-soft (model uninstalled), not changed.

## v3 visibility
`/api/v2/system/portfolio-cadence-status` now: backup=migrated, daily=migrated (legacy retired),
**weekly=migrated (legacy retired)**, monthly/lookthrough=not_migrated.

## Next recommended gate
**Monthly** report cadence (then lookthrough) — same advisory-draft-aware pattern; `db_retention` /
price_cache / destructive cleanup never auto-migrate.
