# Portfolio

- **Page id:** `portfolio`
- **Route:** `/v3/portfolio`
- **Nav group:** Trade
- **Component:** `apps/command-center-v3/src/pages/PortfolioHub.tsx`
- **Owner:** coordinator (builds) · operator (approves)
- **Approved version:** v001
- **Baseline (as built) version:** v000 — captured 2026-10-25, 36 private screenshots
- **Current (verified) version:** none yet — becomes CURRENT only after the post-release visual check passes

## Purpose

Holdings and their analysis: allocation, look-through, returns, dividends, forecast, tax, redeploy, stops.

## Data sources

- `/api/v2/dividends`
- `/api/v2/fidelity-stops/sync`
- `/api/v2/finviz-strip-map`
- `/api/v2/forecast`
- `/api/v2/holdings/live-stops`
- `/api/v2/holdings/monitored-stops`
- `/api/v2/holdings/share-drift`
- `/api/v2/lookthrough/design-fill`
- `/api/v2/overview`
- `/api/v2/portfolio/holdings`
- `/api/v2/portfolio/llm-coverage`
- `/api/v2/portfolio/performance`
- `/api/v2/portfolio/sync/`
- `/api/v2/risk`
- `/api/v2/rotation/propose-etf`
- `/api/v2/rotation/summary`
- `/api/v2/symbol-cards`
- `/api/v2/tax-lots`
- `/api/v2/ui/prefs/get`

## Versions

| Version | State | Approved | Notes |
|---|---|---|---|
| v000 | BASELINE | — | as built 2026-10-25: 36 screenshots at 1440, 412, 390 (private) |
| v001 | APPROVED | 2026-10-24 | Board 12 Look-through (Portfolio › Look-through tab) (back-filled from the handoff) |

How to change this page: design/README.md (propose a new version; never edit an approved one).
