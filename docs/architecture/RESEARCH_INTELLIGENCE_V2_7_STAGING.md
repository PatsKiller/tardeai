# Research Intelligence v2.7 — Stage Trade + Cross-Theme

**Status:** Implemented · **Date:** 2026-07-16  
**Builds on:** v2.6 maturity (conviction, data gates, actions)

## Goals

1. **Stage Trade** — persistent RI ideas with size, funding, stop note  
2. **Cross-theme strips** — income↔retirement, growth/SCHG↔power/AI, infra cluster  
3. **Concentration banner** — SCHG ≥24% or top-3 ≥50%  
4. **CTA hierarchy** — Stage first; incomplete cards demote Stage  

## Staging store

`data/portfolios/state/ri_staged_ideas.json`

| API | Method |
|-----|--------|
| `/api/v2/research-intelligence/staged` | GET |
| `/api/v2/research-intelligence/stage` | POST |
| `/api/v2/research-intelligence/stage/update` | POST (dismiss / patch) |

Incomplete `data_complete=false` → stage rejected.

## Cross-theme

`scripts/lib/research_intelligence_themes.py` — hard-coded relationship graph, zero new network calls.

Card field: `related_themes.items[]` + `impact_note`  
Feed: `portfolio_context.concentration_banner`, `portfolio_context.cross_theme`

## UI

- Concentration banner (session-dismissible)  
- **Staged Ideas** panel + rail  
- Card: Stage Trade / Propose Trim / RI Ideas / Watch / Trading / Stop  
- Related themes chips (click → filter category)  
- Toast on stage  

## Version

Feed `2.7`
