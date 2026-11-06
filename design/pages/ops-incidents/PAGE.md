# Incidents

- **Page id:** `ops-incidents`
- **Route:** `/v3/ops/incidents`
- **Nav group:** Ops
- **Component:** `apps/command-center-v3/src/pages/OpsIncidents.tsx`
- **Owner:** coordinator (builds) · operator (approves)
- **Approved version:** none yet
- **Current (verified) version:** none yet — becomes CURRENT only after the post-release visual check passes

## Purpose

The read view of the incident ledger: incidents by status with their age, and per-incident evidence, actions taken
and PR links. The only writes are the operator's Acknowledge and Close as won't-fix, each recorded in the operator
decisions ledger first. Nothing on this page retries, merges, releases or fixes anything.

Added to the registry by the design-checks merge after the route landed on main; the first design version is to be
proposed under design/README.md.

## Data sources

- `GET /api/v2/ops/incidents`
- `GET /api/v2/ops/incidents/<id>`
- `POST /api/v2/ops/incidents/<id>/ack` (operator only)
- `POST /api/v2/ops/incidents/<id>/close` (operator only)

## Versions

| Version | State | Approved | Notes |
|---|---|---|---|

How to change this page: design/README.md (propose a new version; never edit an approved one).
