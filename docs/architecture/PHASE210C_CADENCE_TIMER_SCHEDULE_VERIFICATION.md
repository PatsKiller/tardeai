# Phase 210C — Cadence Timer Schedule Verification — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T18:55:39-04:00
Measured at: efcc51365 / not measured

Verified all five portfolio-maintenance cadence timers are armed and resolve to correct upcoming fires
(`systemd-analyze calendar`), each triggering the correct service with the correct `--cadence` arg. All
`active/enabled`, `Persistent=true` (missed fires catch up on next boot).

| Cadence | OnCalendar | Next fire | Triggers | Fires in next 7d (06-07→06-14)? |
|---|---|---|---|---|
| backup | `*-*-* 02:30` | Mon 2026-06-08 02:30 | …backup-cadence.service `--cadence backup` | **YES — daily** (06-08…06-14) |
| daily | `Mon-Fri *-*-* 07:30` | Mon 2026-06-08 07:30 | …daily-cadence.service `--cadence daily` | **YES — Mon-Fri** (06-08…06-12) |
| weekly | `Sun *-*-* 20:30` | Sun 2026-06-07 20:30 | …weekly-cadence.service `--cadence weekly` | **YES — today + Sun 06-14** |
| monthly | `*-*-01 07:35` | Wed 2026-07-01 07:35 | …monthly-cadence.service `--cadence monthly` | NO — monthly cadence (next = day-1 July) |
| lookthrough | `Sun *-*-01..07 06:30` | Sun 2026-07-05 06:30 | …lookthrough-cadence.service `--cadence lookthrough` | NO — monthly cadence (next = 1st-Sun July) |

## Verdict
All five schedules are **correct and armed**. Within the literal next-7-day window, **backup, daily, and
weekly fire** (the high-frequency cadences). **monthly and lookthrough are monthly-frequency** — their next
fires (2026-07-01 and 2026-07-05) are correctly scheduled but fall outside a 7-day window by design.
Legacy timers remain `inactive/disabled` (sole path is the cadence timers).
