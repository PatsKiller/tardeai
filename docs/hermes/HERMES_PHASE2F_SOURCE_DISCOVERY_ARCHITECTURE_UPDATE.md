# Hermes Phase 2F — Source Discovery Architecture Update

**Date:** 2026-05-31
**Status:** DESIGN ONLY — no external APIs configured

---

## Current Research Sources

| Source | Type | Status |
|--------|------|--------|
| Trade AI safe views (37 tables + 8 views) | Internal DB | ACTIVE |
| Headless browser (Playwright + Chromium) | Local browsing | ACTIVE (via chat proxy) |
| DuckDuckGo HTML search | Web search | ACTIVE (via browse proxy) |

## Approved Future Sources (require per-source approval)

### Tier 1 — No API key required

| Source | Method | Approval Gate |
|--------|--------|---------------|
| Wikipedia API | Direct HTTP GET | Low risk — factual reference |
| SEC EDGAR | Direct URL pattern | Low risk — public filings |
| Yahoo Finance pages | Headless browser | Low risk — already tested |

### Tier 2 — Existing Trade AI API keys (reuse)

| Source | Key Available | Approval Gate |
|--------|--------------|---------------|
| Brave Search API | Yes (30/day budget) | Medium — reuses existing key |
| Finnhub news | Yes | Medium — already in Trade AI pipeline |
| FRED API | Yes | Low — already in DB via pipeline |

### Tier 3 — New API key required

| Source | Approval Gate |
|--------|---------------|
| SearXNG (self-hosted) | Medium — requires Docker install |
| Grok/xAI challenger | High — external AI model, cost, secrets |
| OpenRouter | High — external AI routing |
| Firecrawl | High — external web scraping service |

## External API Approval Gates

Before any external API is configured for Hermes:

1. Operator must explicitly approve the specific API
2. API key must be stored in hermes_sidecar/.hermes/.env only (not Trade AI .env)
3. Cost/rate limits must be defined
4. No secrets passed to LLM prompts
5. No automatic fallback to paid providers
6. Every external call must be logged
7. Rollback: remove API key from .env

## hermes_research_sources Table

Design exists in `HERMES_SOURCE_DISCOVERY_AND_MEMORY_DESIGN.md`. Not yet created.

Implementation order:
1. Create table (requires DB migration approval)
2. Seed with operator-approved sources
3. Connect Hermes agents to query sources before research
4. Enable source quality scoring and staleness detection
5. Dashboard source management panel

## Safety
| Item | Status |
|------|--------|
| External APIs configured | **ZERO** |
| API keys added | **ZERO** |
| DB migrations | **ZERO** |
| Schema changes | **ZERO** |
