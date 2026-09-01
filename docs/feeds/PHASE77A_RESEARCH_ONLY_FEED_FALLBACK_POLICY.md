# Phase 77A — Research-Only Feed Fallback Policy

Status:      HISTORICAL
as_of:       2026-06-01T12:38:00-04:00
Measured at: efcc51365 / not measured

## Allowed Fallback (Finviz Degraded)

- Create Hermes research backlog item for degraded feed
- Run capped SearXNG discovery for research context only
- Stage research-only source candidates (advisory)
- Label all output: "Finviz degraded — research context only, not screener replacement"

## Forbidden Fallback

- Do NOT generate fake screener CSV rows from search results
- Do NOT replace Finviz GO/WAIT/NO with SearXNG results
- Do NOT create proposals from search results
- Do NOT pretend screener data is fresh when feed is down

## Stale-Data Labeling

All fallback output must include:
- "Finviz feed degraded"
- "Screener data not fresh"
- "Research-only context"
- "Not a trade signal"
- "Operator review required"
