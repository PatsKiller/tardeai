# Phase 206A — Legacy Agent Visibility: Root-Cause Audit — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:25:00-04:00
Measured at: efcc51365 / not measured

## Question
Command Center v3 → System → Hermes shows only the 5 active global profiles (default, tradeai,
tradeai12b, dev, serverops) plus a flat list of retired directory NAMES. The operator wants the
old/legacy agents visible for audit/reference. Why are they missing, and is it safe to show them?

## Where the panel data comes from
- UI: `apps/command-center-v3/src/components/HermesPanel.tsx` (System → Hermes tab).
- Endpoint: `GET /api/v2/hermes/profiles-status` → `scripts/api_v2.py::_hermes_profiles_status`.

## Root cause
`_hermes_profiles_status` builds the profile table by iterating **only `HERMES_PROFILES`** (the 5
active global profiles) via `hermes -p <name> tools list`. It surfaces the retired sidecar dirs as a
**name-only** list (`sidecar_retired_dirs`) and `sidecar_status="rename-retired (rollback/audit only)"`
— it **never scans inside** the retired dirs for their agent/profile/SOUL/wrapper definitions. So the
legacy sidecar identity and the retired wrappers are invisible; only the directory names appear.

## What actually exists in the retired dirs (read-only scan)
Retired sidecar homes (`hermes_sidecar/.hermes.RETIRED_20260606_2140`, `…_2154`) and the retired install
(`hermes_sidecar/install.RETIRED_20260606_2140`) contain:
- **`SOUL.md`** — legacy sidecar identity: *"You are Hermes Agent … created by Nous Research … executing
  actions via your tools."* (the un-hardened generic SOUL — contrast the hardened tradeai/tradeai12b SOULs).
- **`config.yaml`** (+ `.bak`) — legacy profile config: `provider: custom`, `default: gemma3:4b`,
  `base_url: http://127.0.0.1:11434/v1` (local Ollama). Tool policy to be inventoried.
- Runtime state (non-agent): `channel_directory.json`, `gateway_state.json`, caches, sessions, memories, cron.
- **Retired wrappers** (must never be executed): `bin/tirith`, and `hermes`, `hermes-acp`,
  `hermes-agent` in the retired install venv.

The live research-graph agents (Chief Hermes Coordinator, Source Discovery, Hermes Librarian, Embedding
Curator, Promotion Review, Research Backlog Manager, Autonomous Research Manager, SearXNG Docker, Trade AI
safe views) are **still live** and already shown on the separate `/v3/hermes` (HermesHub) page — they are
NOT retired; they are out of scope for this "retired artifacts" section.

## Was the omission intentional?
Partly. The v1.8 migration deliberately surfaced the retired dirs as "rollback/audit only" and kept the
gateway disabled. But the *contents* (legacy SOUL/config/wrappers) were never inventoried into the panel —
the operator now wants that read-only audit view.

## Required conclusions
- Missing because API only exposes active profiles: **YES** (iterates `HERMES_PROFILES`; retired dirs are name-only).
- Retired dirs contain legacy agent definitions: **YES** (SOUL.md, config.yaml, wrappers across 2 `.hermes.RETIRED_*` + 1 `install.RETIRED_*`).
- Safe to display read-only: **YES** (read text + file metadata, redact tokens/keys/env values; never execute).
- Runtime re-enable needed: **NO** (audit/reference only; gateway stays disabled, wrappers never run).

## Plan (206B–206J)
Read-only inventory script → read-only `/api/v2/hermes/legacy-agents` endpoint → read-only "Legacy /
Retired Agents" section under the active profiles in HermesPanel → safety assertions, mapping plan,
validation, screenshot proof, closeout. No runtime/tool/gateway/wrapper enablement anywhere.
