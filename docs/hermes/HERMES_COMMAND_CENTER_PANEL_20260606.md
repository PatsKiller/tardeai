# Hermes Command Center Panel — 2026-06-06

Status:      ACTIVE
as_of:       2026-06-07T14:32:18-04:00
Measured at: efcc51365 / not measured

## Feature overview
A Hermes management area under Command Center → **System → Hermes** tab. Read-only global Hermes/profile
status + safe editing of profile SOUL/identity files + terminal-call reference + a guarded future Codex/dev
setup view. Does NOT enable the retired sidecar gateway and does not touch broker/trading behavior.

## Routes / endpoints added (scripts/api_v2.py)
- `GET  /api/v2/hermes/profiles-status` — version, CLI/venv/home paths, retired-sidecar dirs, gateway
  service active/enabled, per-profile rows (model, tools, status, soul_exists), tools_note.
- `GET  /api/v2/hermes/soul?profile=<name>` — read a profile SOUL.md (identity text only).
- `POST /api/v2/hermes/soul` — save a profile SOUL.md (backup-first, fail-closed safety validation).
- `GET  /api/v2/hermes/codex-dev-status` — future dev/Codex readiness (no OAuth, no creds).
- `GET  /api/v2/hermes/terminal-commands` — copyable chat + diagnostic commands + warning.
Allowed profiles: default, tradeai, tradeai12b, dev, serverops. Path-traversal rejected (allow-list only).

## SOUL editor behavior
Modal (Hermes Identity Editor) per profile: reads current SOUL.md into a textarea; Save creates a
timestamped backup at `~/.hermes/profile_backups/<profile>/SOUL.md.bak_<ts>` BEFORE writing, runs safety
validation, writes only the selected SOUL.md, and shows success (with backup path) or the rejection reasons.

## Safety validation
Fail-closed. Rejects unsafe enabling phrases (execute trades, place orders, modify stops, approve proposals,
read raw secrets, broker credentials, use tools to execute actions, autonomous trading) UNLESS sentence-scoped
negation is present ("You do not …"). For tradeai/tradeai12b, also REQUIRES the boundary lines: do not execute
trades / place orders / modify stops / create-approve-promote proposals / read raw secrets. `.env` is never
editable. Sentence-scoped negation correctly allows e.g. "You do not read raw secrets, API keys, broker
credentials".

## Terminal command panel
Shows copyable `hermes/tradeai/tradeai12b/dev/serverops chat` + diagnostics (version, profile list, config
show, tools list, gateway is-active/is-enabled), with the warning: do not use retired sidecar wrappers;
the retired gateway must remain disabled.

## Codex dev setup behavior
Read-only readiness only: dev profile/SOUL/model presence, codex auth = "not configured", runtime enabled =
false, and a manual terminal instruction block. No web OAuth, no credential storage, no Codex enablement.

## Intentionally NOT enabled
Gateway, Telegram, Discord, Codex runtime, cron/systemd timers — none. No broker/trading/order/stop/
proposal/holdings changes. No secrets read/exposed. Retired sidecar untouched.

## Honest finding (surfaced, not hidden)
The panel reports tool state from the SERVER runtime env. tradeai/tradeai12b currently show `x_search`
(read-only X/Twitter search) auto-enabled because xAI/X credentials exist in the server environment — a
bare shell shows it disabled. The safety-critical toolsets (terminal/file/code_execution/browser/computer_use)
remain DISABLED. The panel names enabled toolsets (e.g. "1 enabled: x_search") and notes the env-dependence
so it is visible rather than misreported as "disabled". Operator may explicitly pin x_search off in the
tradeai/tradeai12b config if desired (separate change).

### Resolution (2026-06-06) — x_search pinned off
`x_search` is now explicitly pinned off for `tradeai` and `tradeai12b` via `disabled_toolsets: [x_search]`
in each profile's `~/.hermes/profiles/<profile>/config.yaml` (the native `tools disable x_search` is a
no-op when the tool is already default-off in a credential-free shell, so the explicit list entry is what
makes the profile policy win over ambient xAI/X credentials). Verified: both profiles now show
**zero enabled tools** in BOTH the bare shell (`tools list`) AND the Command Center runtime view
(`/api/v2/hermes/profiles-status` → `tradeai: disabled`, `tradeai12b: disabled`). **Update:** `default`
was subsequently pinned the same way (`~/.hermes/config.yaml`), so **all three** profiles now show
`disabled` in the runtime view. No credentials were read or removed; no `.env` edited; collector code unchanged.

## Test results
- `python3 -m py_compile scripts/api_v2.py` → OK
- `bash -n scripts/check_system_versions.sh` → OK
- `npm run build` (v3) → OK
- Endpoint smoke: profiles-status/terminal-commands/codex-dev-status/soul → 200
- SOUL save: valid round-trip SAVES (backup created); unsafe content REJECTED with reasons; missing-boundary REJECTED; bad/traversal profile REJECTED.

---
## dev Codex route (2026-06-06)
codex-dev-status now surfaces the verified route: provider openai-codex via OAuth device-code (`hermes auth add openai-codex --type oauth`). Auth is operator-interactive; dev SOUL hardened; dev tools left enabled per operator. See HERMES_DEV_CODEX_SETUP_20260606.md.

---
## dev high-risk tools disabled (2026-06-06)
dev profile: code_execution, terminal, computer_use disabled before Codex login (hard boundary for cloud-backed dev). Panel collector now shows real per-profile tool state even when model unset. See HERMES_DEV_CODEX_SETUP_20260606.md.

---
## Two Hermes layers clarified (2026-06-06)
/v3/hermes = **Hermes Research Agent Graph** (Trade AI research-workflow layer, systemd timers + project scripts). System → Hermes = **Global Hermes Profile** management. Separate subsystems; both kept. SearXNG health confirmed UP (infra _ping hardened 3s->6s). See HERMES_AGENT_GRAPH_MIGRATION_AUDIT_20260606.md.

## Research-graph kill-switch repoint (2026-06-06)
The `/v3/hermes` Research Agent Graph kill-switch banner now reads the canonical live path
**`data/runtime/HERMES_DISABLED`** (was the retired `hermes_sidecar/.hermes/DISABLED`). `_hermes_health`
(`/api/v2/hermes/health`) reads that path and returns `kill_switch_active` + `kill_switch_path`. Banner
wording corrected: `touch` = HALT, `rm` = resume. See `HERMES_RESEARCH_GRAPH_KILL_SWITCH_REPOINT_20260606.md`.

---
## Operator decision: tradeai tool-less (2026-06-07)
tradeai/tradeai12b remain 0 tools by operator decision; advisory-only, no self-fetch. See HERMES_TRADEAI_TOOL_POLICY_DECISION_20260607.md.
