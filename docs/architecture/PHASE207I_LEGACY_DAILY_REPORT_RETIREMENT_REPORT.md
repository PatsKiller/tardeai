# Phase 207I — Legacy Daily Report Retirement Decision — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T11:15:11-04:00
Measured at: efcc51365 / not measured

## Decision: RETIRED (operator-approved 2026-06-07).

> **Update — operator approved immediate retirement.** After all gate conditions passed, the operator
> directed retiring the legacy daily timer now. Done: `systemctl --user disable --now portfolio-daily.timer`
> → now **inactive / disabled**. Unit files **preserved** on disk (not deleted); the cadence timer
> `tradeai-portfolio-daily-cadence.timer` (Mon-Fri 07:30) is the **sole** daily-report path.
> **retired_legacy_count = 1.** Before/after snapshot: `data/runtime/legacy_daily_retirement_20260607/`.
> Rollback: `systemctl --user enable --now portfolio-daily.timer`. (Out of scope, left active: the
> separate `run_alex_daily.py --daily` @05:00 and standalone `portfolio_orchestrator.py` @07:15 cron jobs
> — not what the daily cadence replaces.)

### Original decision (superseded): HOLD — retire NOTHING this phase. Legacy `portfolio-daily.timer` stays ACTIVE.

## Gate conditions (all technically passed)
| condition | status |
|-----------|--------|
| dry-run passed (207D) | ✅ |
| apply run passed (207E) | ✅ exit 0, overall ok |
| output diff passed (207F) | ✅ PASS |
| scheduled/equivalent cycle passed (207H) | ✅ systemd Result=success |
| daily cadence only | ✅ |
| no broker/proposal/protection/trading jobs | ✅ 0/0/0 |
| advisory drafts review-only | ✅ |
| rollback documented | ✅ (207G) |

## Why HOLD despite passing
Per the operator's **Phase 204 lesson** — legacy must not be retired without a *real* parallel-observation
window — and because the daily report is reversible/low-stakes, the legacy timer is **kept active**. The
cycles proven so far are all **same-session** (one manual apply + one systemd-equivalent). Retirement
should follow at least **one real timer-fired parallel cycle**: legacy `portfolio-daily.timer` @07:00 +
`tradeai-portfolio-daily-cadence.timer` @07:30 on Mon 2026-06-08, compared clean.

## Result
- **legacy daily schedule retired count: 0** (nothing retired/commented/disabled).
- Retirement is **APPROVED-PENDING** that one real scheduled parallel cycle → deferred to **Phase 208**.

## Rollback of the pilot schedule (if ever needed)
```
systemctl --user disable --now tradeai-portfolio-daily-cadence.timer
rm ~/.config/systemd/user/tradeai-portfolio-daily-cadence.{service,timer}; systemctl --user daemon-reload
```
Legacy daily path is unaffected.
