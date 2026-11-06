# Risk v002 — SPEC (PROPOSED): the "Regime" tab becomes "Market risk"

Proposed 2026-10-31 (design DSN-20261031-market-risk-ui, engine DSN-20261031-market-risk-engine P3-T2). v000/v001 for Risk
were never captured in this folder; numbered v002 per design/README.md rule 1. Mockups show synthetic data only (private
store, sha256 in status.json). Source: `GET /api/v2/market-risk/latest` and the `market_risk` projection (engine P2-T1),
episodes from P3-T7. Until those exist the tab shows "Market risk: not yet evaluated" above the kept regime panel.

## Page (`/v3/risk`, `RiskHub.tsx`)
Tabs: Exposure · Concentration · Correlation · **Market risk** (was "Regime") · Recovery. Default tab stays Exposure.
The page's purpose line gains "— and what the market itself is signalling".

## Tab "Market risk" (desktop 1440: two columns; phone 390/412: one column, this order)
1. **Tier card**: tier pill + score/100 + since + confirming categories (n of 9) + as_of; Acknowledge button when an Orange
   or Red episode is open (same POST as Home); "de-escalates if" sentence.
2. **Contributors**: the five with points, numbers and as_of; the uplift line (market score → tier after portfolio
   vulnerability and budget breaches).
3. **Nine categories**: technical, breadth, volatility, options flow, macro/credit, cross-asset, event, seasonal,
   extended hours — each a row: state chip (CALM / WARN / STRESS / UNKNOWN), the one number that put it there, its decay
   weight, as_of. UNKNOWN is shown as "unknown — <source> not read since …", never as calm.
4. **Your book vs budget**: each budget (sector, AI basket, growth style, theme, earnings-48h, event cluster, unprotected,
   recent entries) as "actual vs limit" with a bar; breaches first; positions by symbol and distance to stop only.
5. **Probabilities**: table of horizons 4h · 24h · 48h · 72h · 1w · 1m × P(move ≥1.5%), P(move ≥3%), P(up), P(down),
   P(VIX +20%); the analog line ("resembles 2026-03, 2025-03 — explanation only, not scored").
6. **Score history**: 30-session line of the score with tier bands and markers for alerts sent and acks (phone: 10 sessions).
7. **Episodes**: table of alert episodes (opened, tier, repeats, acknowledged at/by, resolved) — the ledger the operator
   can audit; tap → the card text that was sent.
8. **Regime (kept)**: the existing `W7RiskRegime` panel, unchanged, as the last block, titled "Legacy regime label".

## States
Not evaluated · each tier · stale · acknowledged · unavailable ("market risk unavailable — see Ops → Incidents").

## Phone
One column; tier card first; tables scroll sideways inside their card only; ≥44 px targets; ET times.

## Removals / hides / moves (rule 4 — complete list)
- RENAME: tab "Regime" → "Market risk". Its panel is kept inside the new tab as block 8 ("Legacy regime label").
- Nothing hidden or deleted.
