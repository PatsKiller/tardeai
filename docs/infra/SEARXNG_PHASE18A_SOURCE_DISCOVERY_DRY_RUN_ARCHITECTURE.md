# SearXNG Phase 18A — Source Discovery Dry-Run Architecture

**Date:** 2026-05-31
**Status:** APPROVED — dry-run only, file output only

---

## Purpose

Use SearXNG to discover external sources that could enrich Hermes research for specific tickers and themes already in Trade AI's portfolio. This phase produces file-only outputs — no DB writes, no ingestion, no embeddings.

---

## Discovery Categories (Allowed)

| Category | Example Query Theme |
|----------|-------------------|
| ticker_source_discovery | Analyst commentary, news, earnings for specific symbols |
| analyst_source_discovery | Research analysts covering portfolio sectors |
| sector_source_discovery | Sector trends, rotation signals |
| macro_source_discovery | Market breadth, risk indicators, rate environment |
| transcript_source_discovery | Earnings call transcripts, SEC filings |
| SEC_or_filing_source_discovery | 10-K, 10-Q, 8-K, proxy filings |
| portfolio_context_source_discovery | ETF composition, allocation analysis |
| data_quality_source_discovery | Data providers, alternative data sources |

## Discovery Categories (Forbidden)

| Category | Reason |
|----------|--------|
| personal account data | Privacy |
| broker credentials | Security |
| tax data | Privacy |
| private account records | Privacy |
| secrets | Security |
| non-public information | Legal |
| paywalled scraping bypass | Terms of service |
| login-required sources | Authentication scope |
| trading execution instructions | Safety boundary |

---

## Query Rules

- Max 5 queries per dry-run batch
- Max 15 results per query (wrapper default)
- Max 25 total candidates retained across all queries
- Max 10 future-ingestion recommendations
- All queries must be non-personal, non-credential, non-private
- Queries must relate to symbols/themes already in Trade AI portfolio

---

## Output Format

Per dry-run batch, written to `docs/infra/searxng_phase18_source_discovery_dryrun/`:

| File | Content |
|------|---------|
| `source_candidates.json` | Retained candidates with quality scores |
| `rejected_sources.json` | Rejected sources with rejection reason |
| `query_metadata.json` | All queries, timestamps, engines, caps |
| `dry_run_summary.md` | Human-readable summary with findings |
| `future_ingestion_candidates.json` | Top candidates for future staged ingestion |

---

## Scoring Rubric (1–5)

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Source credibility | HIGH | Established financial source? |
| Relevance | HIGH | Directly relevant to portfolio symbols/themes? |
| Freshness | MEDIUM | Content dated within 90 days? |
| Duplicate risk | MEDIUM | Already covered by existing Trade AI pipelines? |
| Privacy/safety | HIGH | No login, no PII, no paywall bypass? |
| Ingestion usefulness | MEDIUM | Would adding this improve Hermes research quality? |
| Operator value | MEDIUM | Would operator benefit from seeing this? |
| Hallucination risk | HIGH | Could this source produce misleading data? |

Score interpretation:
- 4.0+ = Strong candidate for future staged ingestion
- 3.0–3.9 = Marginal, needs operator review
- <3.0 = Reject

---

## No-Ingestion Boundary

This phase MUST NOT:
- Write to any database table
- Call any Trade AI API endpoint that writes
- Create embeddings
- Trigger Hermes staging ingestion
- Modify Hermes research rows
- Call Hermes gateway
- Promote any source

---

## Future Staged-Ingestion Gate

If quality audit passes, Phase 19 would:
1. Create source metadata rows in a dedicated staging table (NOT hermes_research_intelligence)
2. Require operator approval per source
3. Cap at 5 sources per batch
4. Default to --dry-run
5. Require --apply for actual DB write
6. Require separate approval for embeddings
