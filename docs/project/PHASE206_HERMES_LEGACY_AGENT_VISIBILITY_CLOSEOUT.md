# Phase 206 — Hermes Legacy/Retired Agent Visibility — Closeout — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:37:15-04:00
Measured at: efcc51365 / not measured

## Outcome
Command Center v3 → System → Hermes now shows a **read-only "Legacy / Retired Agents"** audit section
below the active profiles, inventorying the retired sidecar artifacts. No runtime behavior changed.

## Root cause
`/api/v2/hermes/profiles-status` iterated only the 5 active `HERMES_PROFILES` and listed retired dirs by
name only — it never scanned their contents. The retired `.hermes.RETIRED_*` / `install.RETIRED_*` dirs
hold legacy SOUL/config (gemma3:4b sidecar identity) + retired wrappers, all previously invisible.

## What was built (read-only)
- `scripts/hermes_legacy_agent_inventory.py` → `data/hermes/legacy_agent_inventory_latest.json` (24 items,
  classified, redacted, never executes wrappers/services).
- `GET /api/v2/hermes/legacy-agents` (`_hermes_legacy_agents`) — read-only, `actions_available=[]`.
- v3 `HermesPanel.tsx` "Legacy / Retired Agents — Read Only" card (banner + classified table, no buttons).
- Docs 206A–206H + mapping plan; screenshot proof.

## Inventory summary
24 items: RETIRED_SOUL 2 · RETIRED_AGENT 1 (gemma3:4b) · RETIRED_WRAPPER 4 (`hermes`/`hermes-acp`/
`hermes-agent`/`tirith`) · UNSAFE_RUNTIME_ARTIFACT 13 · ACTIVE_PROFILE 4. Recommendation: keep retired;
only an operator-approved rebuild of a generic local assistant (hardened SOUL + tools off) is plausible later.

## Safety (all held / verified)
gateway failed/disabled (unchanged) · no retired wrapper executed · no POST/action for retired items ·
no secrets exposed · retired dir mtimes identical before/after (read-only) · tradeai/tradeai12b tools
still disabled · dev/serverops untouched · Codex untouched · no v2 UI · no trading/proposal/protection/
broker/holdings/GO-WAIT/strategy changes · live trading ZERO · Level 7 prohibited.

## Next recommended gate
Operator review of the legacy mapping plan (206F): decide keep-retired (default) vs. an approved rebuild
of one generic local-assistant profile. No code action until then.
