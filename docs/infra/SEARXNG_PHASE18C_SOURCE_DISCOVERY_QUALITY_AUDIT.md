# SearXNG Phase 18C — Source Discovery Quality and Safety Audit

**Date:** 2026-05-31
**Status:** PASS

---

## Quality Metrics

| Metric | Value |
|--------|-------|
| Candidates retained | 25 |
| Score range | 4.1 – 5.0 |
| Mean score | 4.5 |
| Score 5.0 (excellent) | 5 |
| Score 4.0–4.9 (strong) | 20 |
| Score 3.0–3.9 (marginal) | 0 |
| Rejected (<3.0) | 1 |
| Future ingestion candidates (>=4.0) | 10 |

## Rubric Scores

| Dimension | Score | Notes |
|-----------|-------|-------|
| Source credibility | 5/5 | Seeking Alpha, Yahoo Finance, Motley Fool, SEC.gov, Zacks |
| Relevance | 5/5 | All results map to portfolio symbols (SCHD, APAM, TRX, FJSCX) |
| Freshness | 4/5 | Most content dated 2025–2026, some undated |
| Duplicate risk | 4/5 | 0 URL duplicates across queries; some thematic overlap expected |
| Privacy/safety | 5/5 | 0 paywall, 0 login, 0 social media, 0 secrets |
| Ingestion usefulness | 4/5 | Earnings transcripts, analyst upgrades, allocation data directly useful |
| Operator value | 5/5 | Operator would benefit from these sources for manual research |
| Hallucination risk | 4/5 | Established sources reduce risk; Seeking Alpha is opinion, not fact |

**Overall quality score: 4.5/5**

## Source Domain Distribution

| Domain | Count | Type |
|--------|-------|------|
| seekingalpha.com | 4 | Analyst opinion |
| fool.com | 3 | Financial news |
| finance.yahoo.com | 3 | Market data |
| fidelity.com | 2 | Fund provider |
| trxgold.com | 2 | Company IR |
| sec.gov | 1 | Regulatory filing |
| zacks.com | 1 | Research |
| investing.com | 1 | Market data |
| Others | 8 | Various |

## Safety Review

| Check | Result |
|-------|--------|
| Paywall/login sources | ZERO |
| Social media sources | ZERO |
| Secrets in output | ZERO |
| PII in output | ZERO |
| IP addresses in output | ZERO (sanitized) |
| Raw HTML | ZERO |
| DB writes | ZERO |
| Hermes rows | ZERO |
| Embeddings | ZERO |
| Promotions | ZERO |
| Autonomous use | NONE |
| SearXNG binding | 127.0.0.1 (unchanged) |

## Duplication Risk vs Existing Pipelines

| Source Type | Already in Trade AI? | Discovery Value |
|-------------|---------------------|----------------|
| Yahoo Finance news | Partial (news pipeline) | NEW analyst-specific coverage |
| Seeking Alpha analysis | NO | HIGH — new source type |
| SEC filings | Partial (Edgar pipeline) | NEW earnings transcripts |
| Motley Fool analysis | NO | MEDIUM — opinion, not data |
| Company IR pages | NO | HIGH — primary source |
| Zacks research | NO | MEDIUM — fund holdings data |

## Recommendation

**PASS** — Source discovery produced high-quality, relevant, safe results for all portfolio symbols queried. 10 future ingestion candidates are credible, fresh, and non-duplicative with existing Trade AI pipelines. Seeking Alpha and Yahoo Finance earnings transcripts would add significant new intelligence.

**Phase 19 staged ingestion is justified** — the source quality is sufficient to warrant a capped, operator-approved staging phase with the following conditions:
1. Max 5 sources per batch
2. hermes_research_intelligence staging only (not production tables)
3. --dry-run default, --apply required
4. Operator approval per source
5. No auto-ingestion, no autonomous use
6. Separate Phase 20 approval for embeddings
