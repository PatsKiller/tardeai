# Phase 206H — v3 Hermes Legacy Agent Visibility — Screenshot Proof — 2026-06-07

Screenshot: `docs/hermes/PHASE206H_v3_hermes_legacy.png` (Command Center v3 → System → Hermes,
captured via Playwright at `http://localhost:7777/v3/system`, 0 console errors).

## Proof points (all met)
- **Active profiles still visible** — Profiles matrix renders default / tradeai / tradeai12b (Tools =
  `disabled`, green) / dev / serverops.
- **Legacy / Retired agents visible** — red-bordered "Legacy / Retired Agents — Read Only" card below
  the matrix, **20 retired rows** classified RETIRED_SOUL / RETIRED_AGENT (gemma3:4b) / RETIRED_WRAPPER
  (`tirith`, `hermes`, `hermes-acp`, `hermes-agent`) / UNSAFE_RUNTIME_ARTIFACT (gateway_state,
  channel_directory, sandboxes/sessions/caches/pairing).
- **Retired warning visible** — "⚠ Retired sidecar artifacts are shown for audit only. Do not enable
  the retired gateway or execute retired wrappers."
- **Gateway disabled warning visible** — Global Profiles card shows `Gateway service: failed / disabled`
  + "⚠ retired sidecar gateway must remain disabled — do not enable".
- **No enable/run button for retired agents** — the legacy table's only per-row text is the
  Recommendation column (document only / keep retired / unsafe-do-not-use); no buttons.
- **No v2 UI change** — v3 component only.
