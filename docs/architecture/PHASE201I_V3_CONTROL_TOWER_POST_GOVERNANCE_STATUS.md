# Phase 201I — v3 Control Tower Post-Governance Status

Status:      HISTORICAL
as_of:       2026-06-05T10:46:39-04:00
Measured at: efcc51365 / not measured

v3 Queue Control Tower (SystemHub → Control Plane) now distinguishes the full post-governance state.
Read-only; **no v2 UI changed**.

## Distinctions surfaced (all required by 201I)
| Required | Where |
|----------|-------|
| Governance controller active | governance card: controller + last_run ok |
| Retired governance timers | `retired_legacy_timers` **4/4** (new field) |
| Retired governance cron | `retired_legacy_cron` **2** |
| Portfolio-maintenance candidates | `portfolio_maintenance.candidate_count` **8** |
| Portfolio-maintenance NOT migrated | `portfolio_maintenance.status` **not_migrated** (design-only) |
| Safety-net monitors untouched | `safety_net` = freshness_monitor + watchdog **untouched** |
| Live trading prohibited | safety badges + `safety.live_trading=false` |
| Level 7 prohibited | safety badge + `safety.level7=prohibited` |

## Implementation (v3-only, read-only)
- Extended `GET /api/v2/system/governance-pipeline-status` with `retired_legacy_timers`
  (counts disabled governance timers via absence of symlink in `timers.target.wants` — works from the
  API process without `systemctl --user`), `portfolio_maintenance` status, `safety_net` note.
- `PipelineControlTower.tsx` governance card now shows retired timers `4/4`, safety-net untouched, and
  portfolio-maintenance `not_migrated (8 candidates, design-only)`.

## Verified
Endpoint live: `last_run ok · retired_cron 2 · retired_timers 4/4 · portfolio not_migrated 8 ·
safety_net untouched`. v3 `npm run build` clean. `git status | grep command-center-v2` → empty.

---
*v3 control tower reflects post-governance state; portfolio shown as not-yet-migrated; safety net shown
untouched; read-only; no v2 UI.*
