# Phase 206B — Legacy/Retired Agent Inventory Script — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:27:59-04:00
Measured at: efcc51365 / not measured

## Script
`scripts/hermes_legacy_agent_inventory.py` — READ-ONLY. Scans the retired sidecar dirs (and the active
global Hermes home for context) and writes `data/hermes/legacy_agent_inventory_latest.json`.

## Hard guarantees
- Read-only: never executes any agent/wrapper, never starts/enables a service, writes only the one JSON.
- Secret-safe: SOUL/config text scanned only for non-secret fields (model, tools, purpose); any
  key/token/secret/password/env line is **redacted**. Runtime-state file *contents* (gateway_state,
  channel_directory) are **not** read/exposed — presence only.
- No migration/rebuild/re-home.

## Classifications
`ACTIVE_PROFILE | RETIRED_AGENT | RETIRED_WRAPPER | RETIRED_SOUL | UNKNOWN_LEGACY | UNSAFE_RUNTIME_ARTIFACT`

## Per-item fields
name, path, source_dir, status, model, tools, purpose, last_modified, safety_note, migration_recommendation
(keep retired / document only / candidate for manual profile rebuild / unsafe-do-not-use).

## First run result (2026-06-07)
24 items across 3 retired dirs + active home:
- **RETIRED_SOUL ×2** — legacy "Hermes Agent (Nous Research)" un-hardened SOUL (document only).
- **RETIRED_AGENT ×1** — legacy sidecar `config.yaml`, model `gemma3:4b`, local Ollama (candidate for
  manual profile rebuild, operator-approved + hardened SOUL).
- **RETIRED_WRAPPER ×4** — `hermes`, `hermes-acp`, `hermes-agent` (retired install venv), `tirith`
  (retired `.hermes/bin`) → unsafe / do not execute.
- **UNSAFE_RUNTIME_ARTIFACT ×13** — gateway_state/channel_directory + sandboxes/sessions/caches/pairing
  → keep retired, do not revive.
- **ACTIVE_PROFILE ×4** — default/tradeai (gemma3:4b), tradeai12b (gemma3:12b-ctx4k), dev (context only).

Secret-leak check on the output JSON: **0 real values** (only the script's own "Secrets are redacted"
warning text matches the pattern).
