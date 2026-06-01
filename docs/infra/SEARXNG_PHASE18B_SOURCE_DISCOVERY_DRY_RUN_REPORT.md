# SearXNG Phase 18B — Source Discovery Dry-Run Report

**Date:** 2026-05-31
**Status:** COMPLETE — dry-run only, file output only

## Queries Run (5/5 cap)

| # | Query | Results | Engines |
|---|-------|---------|---------|
| 1 | recent analyst commentary SCHD dividend ETF 2026 | 15 | google, startpage, bing, duckduckgo, brave |
| 2 | SEC filing APAM quarterly earnings transcript 2026 | 15 | duckduckgo, google, bing, startpage |
| 3 | gold miners TRX company news earnings 2026 | 15 | bing, duckduckgo, startpage |
| 4 | closed end fund FJSCX portfolio allocation holdings | 15 | startpage, duckduckgo, bing, google |
| 5 | market breadth risk portfolio rotation signals 2026 | 15 | startpage, google, bing |

## Results Summary

| Metric | Value | Cap |
|--------|-------|-----|
| Total results | 75 | — |
| Unique URLs | 75 | — |
| Duplicates | 0 | — |
| Candidates retained (score >= 3.0) | 25 | 25 max |
| Rejected (score < 3.0) | 1 | — |
| Future ingestion candidates (score >= 4.0) | 10 | 10 max |

## Output Files

| File | Path |
|------|------|
| source_candidates.json | docs/infra/searxng_phase18_source_discovery_dryrun/ |
| rejected_sources.json | docs/infra/searxng_phase18_source_discovery_dryrun/ |
| future_ingestion_candidates.json | docs/infra/searxng_phase18_source_discovery_dryrun/ |
| query_metadata.json | docs/infra/searxng_phase18_source_discovery_dryrun/ |
| dry_run_summary.md | docs/infra/searxng_phase18_source_discovery_dryrun/ |

## Top Sources Found

| Score | Source | Symbol/Theme |
|-------|--------|-------------|
| 5.0 | Motley Fool — SCHD dividend ETF analysis | SCHD |
| 5.0 | Seeking Alpha — SCHD upgrade analysis | SCHD |
| 5.0 | Yahoo Finance — TRX Q2 2026 earnings highlights | TRX |
| 5.0 | Seeking Alpha — TRX Gold 60% down analysis | TRX |
| 5.0 | Motley Fool — SCHD vs market analysis | SCHD |

## Scoring Method

Quality score 1–5 based on: source credibility, symbol relevance, freshness (2025/2026 content), paywall/login penalties, social media penalties.

## Safety Confirmations

- [x] 5 queries (at cap)
- [x] 25 candidates retained (at cap)
- [x] 10 ingestion candidates (at cap)
- [x] DB writes: ZERO
- [x] Hermes rows: ZERO
- [x] Embeddings: ZERO
- [x] Promotions: ZERO
- [x] No autonomous use
- [x] No Hermes integration
- [x] SearXNG remains localhost only
- [x] No secrets in outputs
