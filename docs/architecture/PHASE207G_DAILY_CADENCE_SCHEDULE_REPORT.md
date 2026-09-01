# Phase 207G — Daily Cadence Schedule Report — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T11:02:28-04:00
Measured at: efcc51365 / not measured

207F diff PASSED, so the daily cadence is scheduled **in parallel** with the legacy timer (not retired).

## Scheduled
- **scheduled: YES**
- mechanism: **systemd --user timer** (mirrors the backup cadence pattern)
- units: `~/.config/systemd/user/tradeai-portfolio-daily-cadence.{service,timer}`
- command: `run_portfolio_maintenance_pipeline.sh --cadence daily --apply`
- cadence: **Mon-Fri 07:30** (`OnCalendar=Mon-Fri *-*-* 07:30:00`, `Persistent=true`) — 30 min after the
  legacy timer's 07:00, separate cadence lock (`portfolio-maintenance-daily`), no overlap.
- next run: **Mon 2026-06-08 07:30**
- logs: `logs/pipelines/portfolio-maintenance/daily/`

## Parallel observation (legacy kept active)
- **legacy `portfolio-daily.timer` still active + enabled** (next Mon 07:00) — NOT retired.
- Only the daily cadence was scheduled. NOT scheduled: weekly / monthly / lookthrough / db_retention /
  price_cache / secrets-data.
- During the parallel window both run `run_portfolio.sh` (legacy 07:00, cadence 07:30) → duplicate
  review-only advisory drafts/observations daily; tolerable (drafts are date-expired, review-only) and
  intended for output comparison before any retirement.

## Rollback
```
systemctl --user disable --now tradeai-portfolio-daily-cadence.timer
rm ~/.config/systemd/user/tradeai-portfolio-daily-cadence.{service,timer}
systemctl --user daemon-reload
```
Legacy daily path is unaffected by rollback.

## Observation requirement before retirement
Do NOT retire the legacy daily timer until a real scheduled parallel-observation cycle passes (Phase 207H
equivalent + ideally ≥1 actual timer-fired cycle). Retirement is reserved for a later phase.
