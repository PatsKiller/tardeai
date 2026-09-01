# Phase 206F — Legacy Agent → Future Profile Mapping Plan (NO migration) — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:33:09-04:00
Measured at: efcc51365 / not measured

Planning only. **No agent is migrated or rebuilt.** This records what *could* be done later, per item,
for operator decision. Source: `data/hermes/legacy_agent_inventory_latest.json` (24 items).

## Per-item disposition

| Legacy item | Classification | Remain retired? | Rebuild as profile? | Model | Tool policy | SOUL/purpose | Risk | Operator approval |
|-------------|----------------|-----------------|---------------------|-------|-------------|--------------|------|-------------------|
| Legacy sidecar `config.yaml` | RETIRED_AGENT | yes (for now) | **Possible** — only if a generic local assistant is wanted | gemma3:4b (local Ollama) | all toolsets OFF by default (like tradeai) | needs a **hardened** SOUL (the legacy one allows tool actions) | Medium | **Required** |
| Legacy `SOUL.md` ×2 | RETIRED_SOUL | yes | no — **document only** | n/a | n/a | un-hardened "Hermes Agent" identity; do NOT reuse verbatim | Low (text) / High if reused | Required to reuse |
| `hermes`, `hermes-acp`, `hermes-agent` wrappers | RETIRED_WRAPPER | yes | no | n/a | n/a | superseded by global `~/.local/bin/hermes` | **High** (do not execute) | n/a — never run |
| `tirith` wrapper | RETIRED_WRAPPER | yes | no | n/a | n/a | retired sidecar tool | High | n/a |
| gateway_state / channel_directory / sandboxes / sessions / caches / pairing | UNSAFE_RUNTIME_ARTIFACT | **yes (permanent)** | no | n/a | n/a | runtime state, not agent config | High if revived | n/a |

## Live research-fleet agents (NOT retired — context)
The Chief Hermes Coordinator, Source Discovery, Hermes Librarian, Embedding Curator, Promotion Review,
Research Backlog Manager, and Autonomous Research Manager are **live** (coordinator cron */15) and already
surfaced on `/v3/hermes`. They are not part of this retired inventory and need no rebuild.

## Recommendation
Keep everything retired. The only plausible future action is an **operator-approved** rebuild of a generic
local assistant profile from the legacy `config.yaml` — but only with a freshly **hardened** SOUL and
all toolsets disabled (matching the tradeai/tradeai12b safety posture). No action taken now.
