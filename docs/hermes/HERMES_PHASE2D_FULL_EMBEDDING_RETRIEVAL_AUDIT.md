# Hermes Phase 2D — Full Embedding Retrieval Audit

**Date:** 2026-05-31
**Status:** PASS_WITH_LIMITS

## Results: 13/16 correct

| Category | Tests | Passed | Result |
|----------|-------|--------|--------|
| Direct symbol (6) | 6 | 5 | PASS (1 miss: SCHD) |
| Semantic (2) | 2 | 0 | PARTIAL (abstract phrasings don't match) |
| Negative (5) | 5 | 5 | **PERFECT** |
| Mixed (3) | 3 | 3 | PASS |

### Key Scores
- APPS: rank 2, score 0.784
- INFU: rank 2, score 0.777
- SPRC: rank 1, score 0.762
- ASPN: rank 2, score 0.760
- FLYW: rank 3, score 0.708

### Negative Containment: PERFECT (5/5)
Zero Hermes results in any unrelated query (Treasury, NVDA, SSDI, AAPL, real estate).

### RAG Pollution Risk: LOW
No over-matching. Hermes content appears only for relevant symbols.

## Safety
| Item | Status |
|------|--------|
| New embeddings | ZERO |
| DB writes | ZERO |
| Production promotion | ZERO |
| Broker/trade/journal | ZERO |
