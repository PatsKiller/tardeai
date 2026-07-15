# Research Intelligence v2.2 — Portfolio-Aware Advisory

**Status:** Implemented · **Date:** 2026-07-15  
**Builds on:** v2.1 narrative UI + v2.1.3 classification fixes

## Goal

Move from research notes to **holdings-aware recommendations**: named tickers, rough sizing vs live weights, and risk caveats tied to Stop Management.

## Portfolio context

`scripts/lib/research_intelligence_portfolio.py`

- Loads `data/portfolios/state/holdings.json`
- Aggregates **by symbol** across accounts → `weight_pct`, `market_value`
- Concentration flags (≥12% / ≥20%)
- Sleeve totals: income, growth, defense, power_infra, ai_infra

## Advisory fields (every feed item)

| Field | Purpose |
|-------|---------|
| `investment_implications` | What this means for the book |
| `ticker_recommendations[]` | `{ symbol, role, suggested_weight_pct, rationale }` |
| `sizing_guidance` | Allocation language using **current** weights |
| `risk_caveat` | Advisory-only + stop/heat caveats |
| `portfolio_snapshot` | Related weights / sleeves / flags |
| `next_action` | Prefer portfolio-aware CTA |

Roles: `add_candidate` · `trim_candidate` · `hold_review` · `protect` · `plan`

## Responsibility rules

- Sizing always relative to live weights (e.g. “SCHG ~25% — trim 3–6% of book”)
- No order language; stops via Replace mode
- Theme adds capped when sleeve already elevated
- Retirement briefs prioritize MAGI/IRMAA sequencing over new equity risk

## UI

- **Recommended next step** strip expanded: implications, ticker chips, sizing, caveat
- Right rail **Book weights** from feed `portfolio_context`

## Version

Feed `version: "2.2"`
