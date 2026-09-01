# Phase 209B — Monthly Cadence Apply + Diff + Schedule — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T12:11:21-04:00
Measured at: efcc51365 / not measured

## Parallel apply (209E)
`--cadence monthly --apply` → **exit 0, 841s (~14 min — longest chain)**, `overall=ok`. Step
`portfolio_monthly_report` ok (`PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`); price_cache + db_retention
`EXCLUDED_NOT_RUN`. Legacy `portfolio-monthly.timer` left active.
- Artifacts: `data/portfolios/reports/monthly_2026-06-07.docx` + `.json`, `reports_hub.html`.
  (qwen3:14b narrative + Sonnet monthly-report + Opus yaml-advisor steps fail-soft — model/key gated —
  review-only, non-fatal, unchanged.)
- **Safety (window since 15:38Z):** paper_trades 0, proposals 0, protection 0; **no strategy-YAML
  mutation** (0 files touched); GO/WAIT 0; strategy 0.

## Output diff (209F)
`compare_portfolio_daily_outputs.py --cadence monthly` → **PASS (0 unacceptable)** — review-only step ok,
exclusions correct, cadence isolation monthly-only, state fresh, drafts review-only, no destructive/broker.

## Schedule (209G — diff passed)
- systemd `tradeai-portfolio-monthly-cadence.timer` (`OnCalendar=*-*-01 07:35:00`, `Persistent=true`),
  day-1 07:35 — 30 min after legacy day-1 07:05. **Legacy `portfolio-monthly.timer` kept active**
  (parallel). NOT scheduled: lookthrough / db_retention / price_cache.
- Rollback: `systemctl --user disable --now tradeai-portfolio-monthly-cadence.timer && rm
  ~/.config/systemd/user/tradeai-portfolio-monthly-cadence.{service,timer} && systemctl --user daemon-reload`.
