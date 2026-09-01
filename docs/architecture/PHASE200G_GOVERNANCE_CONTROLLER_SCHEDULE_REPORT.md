# Phase 200G — Governance Controller Schedule (legacy kept active)

Status:      HISTORICAL
as_of:       2026-06-04T23:19:30-04:00
Measured at: efcc51365 / not measured

Diff passed (200F), so the governance controller is scheduled via a **systemd user timer** (project
convention — the PHASE41 governance jobs already use user timers). **Legacy cron + PHASE41 timers
remain active as parallel observation; nothing retired yet.**

## Units installed
- `~/.config/systemd/user/tradeai-governance-pipeline.service` — `Type=oneshot`,
  `ExecStart=bash .../scripts/pipelines/run_governance_pipeline.sh --apply`
- `~/.config/systemd/user/tradeai-governance-pipeline.timer` —
  `OnCalendar=Mon-Fri 07:40` + `OnCalendar=Sun 18:00` (`Persistent=true`)
- `systemctl --user enable --now tradeai-governance-pipeline.timer` → enabled; next run **Fri 07:40**.

## Cadence preservation
Legacy governance cadence was weekday ~07:40–07:55 + Sunday ~18:00–18:20 (A1A cron `45 7 * * 1-5`
+ `5 18 * * 0`; PHASE41 timers for facts/status/maturity/readiness). The controller timer fires
weekday 07:40 + Sunday 18:00, bundling all six reporting steps — same windows.

## Parallel observation (intentional, this phase)
- A1A legacy cron lines: **2 active** (unchanged). Crontab: **435 lines (unchanged)**.
- PHASE41 governance systemd timers (facts/status/maturity/readiness): **still active**.
- The underlying scripts keep their own `flock`s, so controller + legacy cannot overlap each other.
- Marked as "parallel observation" — NOT commented/disabled until 200I (after a scheduled cycle).

## Rollback
`systemctl --user disable --now tradeai-governance-pipeline.timer` removes the controller schedule;
legacy jobs continue untouched.

---
*Controller scheduled; legacy active in parallel. No cron retired. Next: observe one cycle (200H).*
