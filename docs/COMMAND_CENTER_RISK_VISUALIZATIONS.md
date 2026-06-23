# Command Center v3 — Risk Visualizations

**Updated:** 2026-06-24  
**Stack:** React + Vite + Recharts (already in `command-center-v3`)  
**Scope:** Broker proposals, options, portfolio, journal, health, home snapshot

---

## Design principle

Risk visuals must answer **one decision per glance**:

1. Is the thesis still valid? (broker proposals)
2. What happens if price moves? (options P/L profile)
3. Where is risk concentrated? (portfolio / position heatmaps)
4. Is the system healthy enough to act? (health strip)

All v1 components live under `apps/command-center-v3/src/components/risk/` and use **Recharts** — no new paid chart licenses required for quick wins.

---

## Implemented (v1 — 2026-06-24)

| Component | Hub / page | What it shows |
|-----------|------------|---------------|
| `ThesisValidityGauge` | Broker Proposals (`ThesisValidityBar`) | 0–100 thesis score ring + zone status |
| `ThesisValidityBar` (enhanced) | Broker proposal cards | Drift gap band: stop · entry · valid zone · target · live dot |
| `PositionSizingRiskBar` | Broker proposal cards | Queued vs account cap — red overflow bar |
| `RiskGauge` | Home snapshot, Health overview | Semicircle gauges (heat, triggered stops, etc.) |
| `RiskContributionBars` | Risk Hub → Exposure | Horizontal max-loss bars by symbol |
| `RiskHeatmapGrid` | Risk Hub, Portfolio Holdings | Color-coded concentration cells |
| `GreeksOverview` | Options → Open Positions | Net Δ, short/long Δ, estimated Θ/day |
| `OptionsPnLProfile` | Options → Open Positions | Expiry P/L curve vs underlying (spot + strike refs) |
| `DrawdownChart` | Journal → Analytics | Underwater / drawdown area (when API provides series) |
| `RiskHealthStrip` | Health Agent overview | 5-gauge system risk dashboard |

### Data sources

| Visual | API / field |
|--------|-------------|
| Thesis band | `thesis_validity` on `/api/v2/broker-proposals` (from `broker_thesis_validity.py`) |
| Portfolio heat | `/api/v2/risk` → `portfolio_heat_pct` |
| Risk contribution | `/api/v2/risk` → `positions[].max_loss` |
| Sector heatmap | `/api/v2/overview` → `sectors[]` |
| Options greeks | `/api/v2/options/positions` → `delta`, `dte`, `unrealized_pnl` |
| Health strip | `/api/v2/health`, `/api/v2/risk`, `/api/v2/health/proposals` |

---

## Library roadmap (2026)

| Priority | Library | Use case | Status |
|----------|---------|----------|--------|
| **Now** | Recharts | Gauges, bars, P/L lines, drawdown | **Shipped** |
| High | SciChart or DXcharts | Live options risk profiles, professional greeks | Planned — evaluate license |
| High | Nivo | Treemap sector/strategy risk, correlation heatmap | Planned — add if treemap needed |
| Medium | Plotly | Vol surface, scenario stress, 3D risk | Future |
| Medium | Lightweight Charts | Price + support/resistance overlay on proposals | Future |

**Recommendation:** Keep Recharts for operator-facing quick wins. Add SciChart/DXcharts only when live streaming greeks and sub-second refresh are required for open options book.

---

## Hub integration map

```
Home (Snapshot)
  └─ RiskGauge ×3: heat · triggered stops · unprotected

Trading → Broker Proposals
  └─ ThesisValidityGauge + drift gap bar + PositionSizingRiskBar per card

Trading → Options
  └─ GreeksOverview + OptionsPnLProfile (book-level, first leg preview)

Risk Hub → Exposure
  └─ Portfolio heat gauge (existing) + RiskContributionBars + RiskHeatmapGrid

Portfolio → Holdings
  └─ Sector RiskHeatmapGrid under allocation donut

Journal → Analytics
  └─ DrawdownChart when edge analytics provides underwater series

Health Agent → Overview
  └─ RiskHealthStrip (heat · score · unprotected · broker stale · options alerts)
```

---

## Quick wins vs longer-term

### Done (week 1)

- Visual drift gap / thesis validity gauge on broker proposals
- Position sizing risk bar (queued vs cap)
- Risk contribution bars + position heatmap on Risk Hub
- Greeks overview + simplified P/L profile on Options
- System health risk strip
- Home snapshot risk gauges

### Medium term (3–6 weeks)

- Per-leg P/L profile inside `OptionPositionCard` (click to expand)
- Full book-level greeks (Θ, Vega) from Schwab chain batch
- Portfolio strategy treemap (Nivo)
- Broker proposal support/resistance overlay on drift gap bar

### Longer term

- Monte Carlo / scenario outcomes (Plotly)
- Correlation matrix heatmap
- SciChart live streaming for options desk

---

## Operator notes

- **Thesis validity** uses entry/stop/target + live quote — not cloud LLM review.
- **Options P/L profile** is expiry approximation — not live greeks-based mark-to-market.
- **Greeks Θ** on the overview panel is estimated from DTE decay — advisory only.
- Hard refresh after deploy: `Ctrl+Shift+R` on Command Center v3.

---

## Files

| Path | Role |
|------|------|
| `apps/command-center-v3/src/lib/riskMath.ts` | Payoff curves, thesis score, contribution weights |
| `apps/command-center-v3/src/components/risk/*.tsx` | Reusable risk visual components |
| `docs/BROKER_PROPOSALS_UI.md` | Broker-specific thesis + curation docs |
| `docs/COMMAND_CENTER_RISK_VISUALIZATIONS.md` | This document |