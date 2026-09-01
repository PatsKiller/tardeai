# Phase 210B — Lookthrough Apply + Diff + Schedule — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T16:58:08-04:00
Measured at: efcc51365 / not measured

## Apply (210E)
`--cadence lookthrough --apply` → exit 0, 3s, `overall=ok`. `portfolio_lookthrough` ok (READ_ONLY_SNAPSHOT);
price_cache + db_retention EXCLUDED. Legacy timer left active. Safety: 0 paper_trades, 0 proposals; no drafts.

## Diff (210F)
`compare_portfolio_daily_outputs.py --cadence lookthrough` → PASS (0 unacceptable) — step ok+READ_ONLY_SNAPSHOT,
exclusions correct, cadence isolation lookthrough-only, state fresh, no destructive/broker.

## Schedule (210G)
systemd `tradeai-portfolio-lookthrough-cadence.timer` (`OnCalendar=Sun *-*-01..07 06:30:00` = 1st Sunday
06:30), parallel to legacy `portfolio-lookthrough.timer` (1st-Sun 06:00, kept active). Rollback:
`systemctl --user disable --now tradeai-portfolio-lookthrough-cadence.timer && rm
~/.config/systemd/user/tradeai-portfolio-lookthrough-cadence.{service,timer} && systemctl --user daemon-reload`.

## Observe (210H)
systemd-equivalent cycle: Result=success, ExecMainStatus=0, overall=ok; comparator PASS.
