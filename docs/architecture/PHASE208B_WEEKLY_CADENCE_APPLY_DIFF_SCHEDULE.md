# Phase 208B — Weekly Cadence Apply + Diff + Schedule — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T11:26:53-04:00
Measured at: efcc51365 / not measured

## Parallel apply (208E)
`--cadence weekly --apply` → **exit 0, 269s**, `overall=ok`. Step `portfolio_weekly_report` ok
(`PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`); price_cache + db_retention `EXCLUDED_NOT_RUN`. Legacy
`portfolio-weekly.timer` left active.
- Artifacts produced: `data/portfolios/reports/portfolio_dashboard_2026-06-07_weekly.html`,
  `portfolio_brief_2026-06-07_weekly.docx`. (qwen3:14b narrative + Opus YAML advisor steps fail-soft —
  model/key gated — review-only, non-fatal, unchanged.)
- Advisory drafts: review-only (drafts 13 stable, observations idempotent).
- **Safety (window since 15:19Z):** paper_trades changed 0, proposals 0, protection advisories 0;
  **no strategy YAML mutation** (`config/strategies/*.yaml` untouched by the run); GO/WAIT 0; strategy 0.

## Output diff (208F)
`compare_portfolio_daily_outputs.py --cadence weekly` (comparator generalized to take `--cadence`) →
**PASS (0 unacceptable)**: review-only step ok, exclusions correct, cadence isolation weekly-only, state
fresh, drafts review-only, no destructive/broker steps. Daily regression still PASS.

## Schedule (208G — diff passed)
- **scheduled: YES** — systemd `tradeai-portfolio-weekly-cadence.timer`
  (`OnCalendar=Sun *-*-* 20:30:00`, `Persistent=true`), next **Sun 2026-06-07 20:30**.
- command: `run_portfolio_maintenance_pipeline.sh --cadence weekly --apply`; weekly-specific lock/log.
- **legacy `portfolio-weekly.timer` kept active** (Sun 20:00) — parallel, 30-min offset.
- NOT scheduled: monthly / lookthrough / db_retention / price_cache / secrets-data.
- Rollback: `systemctl --user disable --now tradeai-portfolio-weekly-cadence.timer && rm
  ~/.config/systemd/user/tradeai-portfolio-weekly-cadence.{service,timer} && systemctl --user daemon-reload`.
