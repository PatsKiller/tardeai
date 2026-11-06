# Risk

- **Page id:** `risk`
- **Route:** `/v3/risk`
- **Nav group:** Trade
- **Component:** `apps/command-center-v3/src/pages/RiskHub.tsx`
- **Owner:** coordinator (builds) · operator (approves)
- **Approved version:** v002
- **Current (verified) version:** none yet — becomes CURRENT only after the post-release visual check passes

## Purpose

Exposure, concentration, correlation, regime and recovery, with stop protection per position.

## Data sources

- `/api/v2/correlation`
- `/api/v2/recovery`

## Versions

| Version | State | Approved | Notes |
|---|---|---|---|
| v001 | APPROVED | 2026-10-24 | Board 15 Risk (back-filled from the handoff) |
| v002 | APPROVED | 2026-10-31 | Market-risk tab: tier, contributors, category states, budgets (DSN-20261031-market-risk-ui) |

How to change this page: design/README.md (propose a new version; never edit an approved one).
