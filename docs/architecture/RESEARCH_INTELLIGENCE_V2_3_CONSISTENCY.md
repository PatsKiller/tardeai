# Research Intelligence v2.3 — Consistent Portfolio-Aware Recommendations

**Status:** Implemented · **Date:** 2026-07-15  
**Builds on:** v2.2 portfolio advisory + v2.2.2 stub/retirement CTA fixes  
**CC surface:** Command Center v3 only (`/v3/` Research Intelligence hub)

## Goal

Deliver **consistently mature, decision-ready** briefs: deep narrative, category-correct advisory, and **ticker + sizing guidance** that always references live portfolio allocations, concentration, and stops — not recycled SCHD/JEPI sleeve spam.

## What changed in v2.3

### 1. Category-gated advisory (all primaries)

`scripts/lib/research_intelligence_portfolio.py` · `build_advisory`

| Primary | Portfolio-aware behavior |
|---------|--------------------------|
| `risk_regime` / stop types | Named protect when held; else top weights as **protect** reviews + concentration flags |
| `retirement_tax` | Title-specific CTAs (IRMAA / MAPT / SSDI / Roth ladder / monitor) — no identical blurb |
| `dividend_income` | Full income sleeve only for strategy titles; single-name titles → position review only |
| `sector_thematic` / `macro_geo` | Theme from **title**; held peers + add candidates; SCHG funding when growth heavy |
| `company_ticker` / `catalyst_event` | Single-symbol sizing with % of book + $ MV; off-book = watchlist starter only |
| `compounding_wealth` | Growth sleeve + SCHG hold/trim language |
| other / academic | Concentration reference (SCHG/flags) — no invented shopping lists |

Hard classification: options desk / autonomous thesis titles force `company_ticker` so income-sleeve recs cannot bleed in.

### 2. Narrative depth polish

`scripts/lib/research_intelligence_narrative.py` · `_polish_narrative_depth`

- Strips monitor boilerplate; rebuilds thin bodies from implications + sizing + why-it-matters
- Topic monitors use **category-aware** copy (retirement / income / risk / general)
- Ensures bull/bear, takeaways, and quality tier
- **Quality tiers:** `A` (LLM + deep body + advisory), `B` (solid body + action/ticks), `C` (thin)

### 3. Ranking

Feed sort boosts quality tier, ticker recs, sizing text, and bull/bear pairs; still demotes stop noise and monitor stubs.

### 4. UI (CC v3)

`ResearchIntelligenceHub.tsx`

- **Tier A/B/C** and **Ticker recs** badges
- Action strip: stronger visual hierarchy for implications, ticker chips (with current weights), and **sizing guidance** panel
- Card view: compact ticker chips with allocation hints
- “Portfolio-aware” marker when advisory present

## Success criteria

- Relevant cards cite **current** weights (e.g. “SCHG ~25.6% — consider trim 3–6% of book”)
- Company/options briefs do **not** recycle full SCHD/JEPI lists
- Retirement pillar stays frequent, topic-specific, tax-first
- Risk caveats always present; no order language

## Version

Feed `version: "2.3"`

## Operator notes

1. Hard-refresh `/v3/` after dist rebuild (sessionStorage build-meta cache bust).
2. Holdings SSOT: `data/portfolios/state/holdings.json` (via portfolio_server).
3. Enrichment still optional for LLM narrative; synthesized path remains advisory-complete.
