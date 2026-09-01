# Phase 71D — Feed Fallback Policy

Status:      HISTORICAL
as_of:       2026-06-01T11:55:37-04:00
Measured at: efcc51365 / not measured

| Feed | Primary | Fallback | Scope |
|------|---------|----------|-------|
| Finviz screener | FINVIZ_COOKIE (CSV) | FINVIZ_API_TOKEN (if supported) | Symbol scanning |
| News | Multi-source pipeline | SearXNG manual | Research context only |
| Catalyst | catalyst_enrichment.py | SearXNG discovery | Advisory only |
| SEC filings | Existing pipeline | SearXNG discovery | Advisory only |

SearXNG is NEVER a direct screener replacement — it's a research fallback only.
