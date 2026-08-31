# Phase 208B — Hermes Identity & Profile Inventory (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:26:30-04:00
Measured at: efcc51365 / not measured

Script: `scripts/audit_hermes_identities.py` → `data/hermes/hermes_identity_audit_latest.json` (read-only, no secrets).

## Counts
- ACTIVE_GLOBAL_PROFILE: 5
- ACTIVE_RESEARCH_FLEET_AGENT: 7
- RETIRED_SIDECAR_PROFILE: 2 · RETIRED_RUNTIME_ARTIFACT: 1 · RETIRED_WRAPPER: 2 (stubs, exit 2)
- Duplicate active SOUL hashes: NONE → no conflicting/duplicate active identities.

## Active global profiles (System → Hermes)
| Profile | Model | Tools enabled | Safety | Rec |
|---------|-------|---------------|--------|-----|
| default | gemma3:4b | 0 | general | keep active |
| tradeai | gemma3:4b | 0 | restricted advisory | keep active |
| tradeai12b | gemma3:12b-ctx4k | 0 | restricted advisory | keep active |
| dev | unset | 14 (terminal/code_exec/computer_use OFF) | dev; cloud-data SOUL guard | keep active |
| serverops | unset | 17 (incl terminal/code_exec) | **future/unconfigured** | keep active; harden before use |

## Active research-fleet agents (/v3/hermes graph; project .venv + systemd timers, NOT profiles)
coordinator · source_discovery · librarian · embedding_curator · promotion_review · backlog_manager ·
autonomous_research — all 7 backing scripts present under `scripts/hermes_*.py`. Reads Trade AI safe views;
staging/advisory only; no broker.

## Retired (audit-only)
.hermes.RETIRED_20260606_2140, .hermes.RETIRED_20260606_2154 (sidecar profiles), install.RETIRED_20260606_2140
(runtime), + run_hermes_readonly.sh / run_hermes_gateway.sh (retirement stubs). Read-only; never executed.

## Conclusions
- No UNKNOWN_ORPHAN or POSSIBLE_CONFLICT identities. No duplicate active SOULs.
- Two layers confirmed distinct: global profiles (chat) vs research-fleet agents (workflow). Retired sidecar
  is a third, dormant, audit-only layer.
- Risk-register item: serverops (and dev) carry tool sets while unconfigured; serverops still has dangerous
  tools — harden before it is ever given a model/connected.
