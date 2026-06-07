# Phase 207I — Legacy Daily Report Retirement Decision — 2026-06-07

## Decision: HOLD — retire NOTHING this phase. Legacy `portfolio-daily.timer` stays ACTIVE.

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
