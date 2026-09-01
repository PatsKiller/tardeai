# Phase 208J — Hermes Agent Risk Register (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:34:47-04:00
Measured at: efcc51365 / not measured

| ID | Risk | Level | Status / Action |
|----|------|-------|-----------------|
| R1 | Disabled `hermes-gateway.service` unit still has sidecar ExecStart | P2 | Inert (disabled). Repoint/remove unit file (operator-approved). |
| R2 | `serverops` profile has 17 tools incl terminal/code_execution while unconfigured (no model) | P1 | HOLD — harden (disable dangerous tools) before serverops is ever given a model/connected. |
| R3 | Coordinator kill-switch references retired `hermes_sidecar/.hermes/DISABLED` (stale path) | P1 | Repoint to a live path (e.g. data/runtime/HERMES_DISABLED) — separate operator-approved change. |
| R4 | `dev` will get a cloud Codex model; retains file/browser/messaging/cronjob tools | P1 | terminal/code_execution/computer_use already disabled; SOUL bars secrets-to-cloud. Optional: tighten file/browser. |
| R5 | Research fleet runs live every 15 min (auto-promote/embed) | P1→accepted | Operator directive B; reversible+audited; all timers success; kill-switch path (R3) needs repoint. |
| R6 | Codex auth pending (operator-interactive) | P2 | Documented; no auto-config; no creds stored. |
| R7 | Retired sidecar dirs retained | P2 | Keep retired (rollback/audit); proven non-dependency (208F). |

## P0: none found. No risk can break the live research/advisory flow today.
## Urgent (P1): R2 serverops hardening, R3 kill-switch repoint (both operator-gated).
