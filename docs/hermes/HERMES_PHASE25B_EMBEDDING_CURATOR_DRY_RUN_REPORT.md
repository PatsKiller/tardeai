# Hermes Phase 25B — Embedding Curator Dry-Run Report

**Date:** 2026-06-01
**Status:** COMPLETE — dry-run only, zero embeddings created

## Scope

- Total rows: 23
- Already embedded (skipped): 7 (ids 1–7)
- Rejected (backlog tasks): 5 (ids 19–23, not findings)
- Rejected (low confidence): 1 (TELO id=9, conf 0.2)
- Scored candidates: 10
- Future pilot recommendations: 2 (max 2 cap)

## Pilot Recommendations

| Rank | ID | Symbol | Type | Score | Key Strength |
|------|-----|--------|------|-------|-------------|
| 1 | 12 | SCHD | source_discovery | 4.55 | SA upgrade article, income-gap relevant, external URL |
| 2 | 13 | TRX | source_discovery | 4.36 | Yahoo Finance Q2 earnings, portfolio relevant, external URL |

Both are SearXNG-sourced with credible external URLs, making them high-value RAG additions that bring genuinely new external information into the embedding space.

## All Scored Candidates

| ID | Symbol | Type | Score | Conf | URL? |
|----|--------|------|-------|------|------|
| 12 | SCHD | source_discovery | 4.55 | 0.50 | YES |
| 13 | TRX | source_discovery | 4.36 | 0.50 | YES |
| 16 | TRX | source_discovery | 4.36 | 0.50 | YES |
| 14 | APAM | source_discovery | 4.18 | 0.48 | YES |
| 15 | FJSCX | source_discovery | 4.18 | 0.48 | YES |
| 17 | ADBE | ticker_thesis_challenge | 3.73 | 0.60 | NO |
| 18 | AGMH | ticker_thesis_challenge | 3.73 | 0.60 | NO |
| 8 | FJSCX | ticker_thesis_challenge | 3.55 | 0.60 | NO |
| 10 | APAM | ticker_thesis_challenge | 3.55 | 0.60 | NO |
| 11 | TRX | ticker_thesis_challenge | 3.55 | 0.60 | NO |

## Rejected

| ID | Symbol | Reason |
|----|--------|--------|
| 1–7 | Various | Already embedded |
| 9 | TELO | Confidence 0.2 below threshold |
| 19–23 | Various | Research backlog tasks, not findings |

## Safety

- [x] DB writes: ZERO
- [x] Embeddings created: ZERO
- [x] content_embeddings writes: ZERO
- [x] Hermes row mutations: ZERO
- [x] Promotions: ZERO
- [x] File output only
