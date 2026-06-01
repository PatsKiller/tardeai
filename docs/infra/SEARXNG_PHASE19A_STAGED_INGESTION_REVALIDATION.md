# SearXNG Phase 19A — Staged Ingestion Candidate Revalidation

**Date:** 2026-05-31
**Status:** COMPLETE — 5 candidates eligible

---

## Candidate Selection (5 of 10)

Selected for maximum symbol coverage and source diversity:

| # | Symbol | Source | Title | Score | Reason |
|---|--------|--------|-------|-------|--------|
| 1 | SCHD | seekingalpha.com | SCHD: The Buying Opportunity Is Finally Flashing (Upgrade) | 5.0 | New analyst opinion source for SCHD |
| 2 | TRX | finance.yahoo.com | TRX Gold Corp (TRX) Q2 2026 Earnings Call Highlights | 5.0 | New earnings data for TRX |
| 3 | APAM | fool.com | APAM Q1 2026 Earnings Transcript | 4.8 | New earnings transcript for APAM |
| 4 | FJSCX | zacks.com | FJSCX - Fidelity Japan Small Companies Fund - Holdings | 4.8 | New fund holdings source |
| 5 | TRX | seekingalpha.com | TRX Gold: Down 60% From Highs, And The Catalyst List Is Growing | 5.0 | New analyst perspective on TRX |

## Validation Checks

| Check | Result |
|-------|--------|
| Provenance traced to Phase 18B query | YES — all 5 from future_ingestion_candidates.json |
| Quality score >= 4.0 | YES — range 4.8–5.0 |
| No secrets in content | PASS |
| No private/personal data | PASS |
| No paywall/login bypass | PASS |
| No social media | PASS |

## Duplicate Risk

| Symbol | Existing Hermes rows | Duplicate? |
|--------|---------------------|-----------|
| SCHD | id=3 (news_research_reframe) | NO — different research type (source_discovery vs news_reframe) |
| TRX | id=11 (ticker_thesis_challenge) | NO — different research type, new external source |
| APAM | id=10 (ticker_thesis_challenge) | NO — different research type, earnings transcript |
| FJSCX | id=8 (ticker_thesis_challenge) | NO — different research type, fund holdings |

No URL duplicates in existing hermes_research_intelligence.source_urls_json.

## Schema Fit

Target: `hermes_research_intelligence`

- `source` = 'hermes' (CHECK constraint requires this; provenance tracked in evidence_json)
- `research_type` = 'source_discovery' (new type, no CHECK constraint on this column)
- `hermes_agent_name` = 'source_discovery_agent'
- `model_used` = 'searxng_manual' (no LLM, manual search)
- `status` = 'staged' (always)
- `confidence_score` = quality_score normalized to 0–1 scale

Schema fits cleanly. No dedicated table needed for 5 rows.

## Rollback Plan

```sql
DELETE FROM hermes_research_intelligence
WHERE research_type = 'source_discovery'
  AND hermes_agent_name = 'source_discovery_agent';
```
