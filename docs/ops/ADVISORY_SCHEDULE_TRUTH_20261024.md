# Advisory schedule: advertise observed fires only

**Status:** Board 8 backend review unit; shared-frame UI follows W5.
**Owner:** W6, `codex-w6-desks-b-20261024`.
**Updated:** 2026-10-24.

Design-Task: `DSN-20261024-desks-b-P1-T1`.

The schedule adapter previously fell back to the next weekday at 09:15 whenever
systemd supplied no next-fire timestamp. A disabled timer therefore appeared to
have a scheduled run. The backend now requires observed timer properties and a
verified future fire. It reads `systemctl --user show` only; it changes no timer,
schedule, registry, dispatch or run-now behavior.

| UI element | API / field | Source / key | Writer or authority |
|---|---|---|---|
| Schedule state and gap | `/api/v3/advisory` → `schedule.schedule_state`, `schedule_reason` (also run-status) | `LoadState`, `ActiveState`, `UnitFileState`, `NextElapseUSecRealtime` from `tradeai-advisory-shadow-session.timer` | Host systemd timer status, observed read-only |
| Next scheduled run | `schedule.next_run_at`, `next_run_et` | Only an observed future `NextElapseUSecRealtime` from a loaded, active, non-disabled/non-masked timer | Same systemd timer; no calendar fallback |
| Timer flags | `schedule.timer_enabled`, `timer_active` | Observed unit-file and active-state properties; unknown property → null | Same read-only observation |
| Observation age | `schedule.observed_at` | Time the timer properties were read, cached at most 60 seconds | Adapter observation clock, not job-success time |
| Declared cadence | `schedule.cadence` | Existing weekday 09:15 declaration in `advisory_desk_schedule.py` | Configuration declaration only; never proof of a future run |

States: `SCHEDULED`, `DISABLED`, `INACTIVE`, `MISSING`, `UNKNOWN`. Every state
except `SCHEDULED` returns null next-run fields and a reason. A timestamp that
has elapsed since the property read is withheld until a fresh future fire can be
observed. Both numeric microseconds and the timestamp formats systemctl renders
are parsed; ambiguous zones, timezone-free values and invalid clocks remain gaps.

This unit does not claim that the existing page's calendar fallback has been
removed. W6 will replace that UI fallback when adopting W5's DeskPage frame. W8
owns moving the opinion writer to a monitored n8n lane; neither this code nor its
tests enable a writer. W5's shared source strip remains the lane-state/success
clock owner.

The fixture suite pins the observation window and tests disabled-with-timestamp,
inactive, missing, failed query, invalid/future/elapsed timestamps and cache TTL.
Existing run-now and wave-C tests continue to use local mocks and temporary
stores. CRLF in the existing schedule module and run-now tests is preserved.

Read-only host property receipt and replay:
[`timer-observation.json`](packets/advisory-schedule-truth-20261024/timer-observation.json).
