# Embedding Curator Dry-Run Summary

**Date:** 2026-06-01 02:20 UTC

**Total rows:** 23
**Already embedded (skipped):** 7
**Rejected (backlog tasks):** 5
**Rejected (low confidence):** 1
**Scored candidates:** 10
**Future pilot recommendations:** 2 (max 2)

**DB writes: ZERO | Embeddings created: ZERO | Promotions: ZERO**

---

## Pilot Recommendations

### ID 12 — SCHD (source_discovery)
Overall score: 4.55
Confidence: 0.5 | Has URL: True | Model: searxng_manual
Preview: Seeking Alpha upgrades SCHD to Buy, citing remarkable resilience amid rising bond yields. External a
Scores: {"evidence_quality": 4, "source_quality": 5, "freshness": 5, "uniqueness": 4, "retrieval_usefulness": 5, "rag_pollution_risk": 4, "actionability_support": 4, "duplication_risk": 4, "operator_value": 5, "portfolio_relevance": 5, "income_gap_relevance": 5}

### ID 13 — TRX (source_discovery)
Overall score: 4.36
Confidence: 0.5 | Has URL: True | Model: searxng_manual
Preview: Yahoo Finance reports TRX Q2 2026 highlights: quarterly production record of ~7,500 ounces, record a
Scores: {"evidence_quality": 4, "source_quality": 5, "freshness": 5, "uniqueness": 4, "retrieval_usefulness": 5, "rag_pollution_risk": 4, "actionability_support": 4, "duplication_risk": 4, "operator_value": 5, "portfolio_relevance": 5, "income_gap_relevance": 3}

## All Scored Candidates

- [4.55] id=12 SCHD   source_discovery          conf=0.5
- [4.36] id=13 TRX    source_discovery          conf=0.5
- [4.36] id=14 APAM   source_discovery          conf=0.48
- [4.36] id=15 FJSCX  source_discovery          conf=0.48
- [4.36] id=16 TRX    source_discovery          conf=0.5
- [3.91] id=8 FJSCX  ticker_thesis_challenge   conf=0.6
- [3.91] id=10 APAM   ticker_thesis_challenge   conf=0.6
- [3.91] id=11 TRX    ticker_thesis_challenge   conf=0.6
- [3.91] id=17 ADBE   ticker_thesis_challenge   conf=0.6
- [3.91] id=18 AGMH   ticker_thesis_challenge   conf=0.6

## Rejected

- id=1 FLYW   — already_embedded
- id=2 SPRC   — already_embedded
- id=3 SCHD   — already_embedded
- id=4 APPS   — already_embedded
- id=5 INFU   — already_embedded
- id=6 ASPN   — already_embedded
- id=7 SYSTEM — already_embedded
- id=9 TELO   — confidence_0.2_below_0.3
- id=19 SYSTEM — research_backlog_task_not_finding
- id=20 TELO   — research_backlog_task_not_finding
- id=21 APAM   — research_backlog_task_not_finding
- id=22 FJSCX  — research_backlog_task_not_finding
- id=23 SYSTEM — research_backlog_task_not_finding