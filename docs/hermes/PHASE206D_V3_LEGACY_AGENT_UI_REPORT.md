# Phase 206D — v3 Hermes UI: Legacy / Retired Agents Section — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:32:19-04:00
Measured at: efcc51365 / not measured

## Change
`apps/command-center-v3/src/components/HermesPanel.tsx` (Command Center v3 → System → Hermes) only.
Added a read-only **"Legacy / Retired Agents — Read Only"** card directly below the active Profiles matrix.

## What it shows
A red-bordered audit card with a red banner *"Retired sidecar artifacts are shown for audit only. Do not
enable the retired gateway or execute retired wrappers."* and a table of retired items (active profiles are
excluded — they're already in the Profiles matrix):

| Name | Source (retired dir) | Classification | Model | Tools | Purpose / Safety | Modified | Recommendation |

Classification colored: `RETIRED_WRAPPER` / `UNSAFE_RUNTIME_ARTIFACT` red; `RETIRED_AGENT` / `RETIRED_SOUL`
amber. Header shows item count, live gateway state, and last-scan time.

## Required UI behavior (met)
- Retired agents **visually separated** from active profiles (own red-bordered card, below the matrix).
- **No** active/run/enable buttons; **no** edit-SOUL action for retired items.
- No per-item "View Config/SOUL" file-reader was added (optional in spec) — to keep zero file-read action
  surface; the audit fields (model/tools/purpose/safety) come from the redacted inventory.
- Banner present; data is read-only from `/api/v2/hermes/legacy-agents`.

## Source / safety
Data: `GET /api/v2/hermes/legacy-agents` (read-only, redacted, `actions_available=[]`). v3 build OK.
**No v2 UI changed.** No new POST/action route. Retired gateway/wrappers never invoked from the UI.
