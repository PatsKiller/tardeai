# Health

- **Page id:** `health`
- **Route:** `/v3/health`
- **Nav group:** Ops
- **Component:** `apps/command-center-v3/src/pages/HealthHub.tsx`
- **Owner:** coordinator (builds) · operator (approves)
- **Approved version:** v001
- **Current (verified) version:** none yet — becomes CURRENT only after the post-release visual check passes

## Purpose

Platform health, including the shared Jobs & health view.

## Data sources

- `/api/v2/health`
- `/api/v2/health/activity`
- `/api/v2/health/coders`
- `/api/v2/health/dispatches`
- `/api/v2/health/history`
- `/api/v2/health/proposals`
- `/api/v2/health/remediate`
- `/api/v2/risk`

## Versions

| Version | State | Approved | Notes |
|---|---|---|---|
| v001 | APPROVED | 2026-10-24 | Board 16 Jobs & health (embedded) (back-filled from the handoff) |

How to change this page: design/README.md (propose a new version; never edit an approved one).
