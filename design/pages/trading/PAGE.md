# Trading

- **Page id:** `trading`
- **Route:** `/v3/trading`
- **Nav group:** Trade
- **Component:** `apps/command-center-v3/src/pages/TradingHub.tsx`
- **Owner:** coordinator (builds) · operator (approves)
- **Approved version:** none yet
- **Baseline (as built) version:** v000 — captured 2026-10-25, 51 private screenshots
- **Current (verified) version:** none yet — becomes CURRENT only after the post-release visual check passes

## Purpose

Trade AI, options, open trades and proposals.

## Data sources

- `/api/v2/broker-orders/pilot/status`
- `/api/v2/broker-proposals`
- `/api/v2/broker-proposals/summary`
- `/api/v2/broker-reconciliation`
- `/api/v2/execution/current-state`
- `/api/v2/open-trades/intelligence`
- `/api/v2/paper-proposals`
- `/api/v2/paper-status`
- `/api/v2/paper-trade-readiness`
- `/api/v2/trade-ai/scanner`
- `/api/v2/warrior-audit/latest`

## Versions

| Version | State | Approved | Notes |
|---|---|---|---|
| v000 | BASELINE | — | as built 2026-10-25: 51 screenshots at 1440, 412, 390 (private) |

How to change this page: design/README.md (propose a new version; never edit an approved one).
