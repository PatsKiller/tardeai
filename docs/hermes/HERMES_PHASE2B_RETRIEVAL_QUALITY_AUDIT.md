# Hermes Phase 2B — Retrieval Quality Audit

**Date:** 2026-05-30
**Status:** PASS_WITH_LIMITS

---

## 1. Summary

Audited the 2 pilot Hermes embeddings (FLYW id=26858, INFU id=26859) across 8 retrieval queries in 4 categories. **7/8 tests correct.** Direct retrieval strong, negative containment perfect, one semantic query missed (expected — embedding text didn't match alternative phrasing).

---

## 2. Pilot Embedding Verification

| ID | source_type | source_id | Title | Model | Dim |
|----|-------------|-----------|-------|-------|-----|
| 26858 | hermes_research | 1 | FLYW — ticker_thesis_challenge (Phase 1E) | nomic-embed-text | 768 |
| 26859 | hermes_research | 5 | INFU — ticker_thesis_challenge (Phase 1H) | nomic-embed-text | 768 |

- Total Hermes embeddings: **2** (no extras)
- Queue: 2 items, both completed
- No additional embeddings since Phase 2A

---

## 3. Retrieval Test Matrix

### A. Direct Symbol Relevance

| Test | Query | Hermes Found | Rank | Score | Result |
|------|-------|-------------|------|-------|--------|
| A1 | FLYW trade thesis challenge losses stop hit | YES | 5 | 0.734 | **PASS** |
| A2 | INFU trade thesis challenge mixed outcomes | YES | **1** | **0.832** | **PASS** |

INFU retrieved at rank 1 with highest score (0.832). FLYW at rank 5 (0.734) — still in top results but behind some existing Trade AI content.

### B. Semantic Relevance

| Test | Query | Hermes Found | Rank | Score | Result |
|------|-------|-------------|------|-------|--------|
| B1 | payment processing company repeated trading losses | NO | — | — | **FAIL** |
| B2 | healthcare infusion services trade analysis | YES | 7 | 0.505 | **PASS** |

B1 failed — "payment processing company" is too abstract for FLYW's embedding text which focuses on trade data, not company description. B2 passed at rank 7 with marginal score (0.505).

### C. Negative / Unrelated Queries

| Test | Query | Hermes Found | Result |
|------|-------|-------------|--------|
| C1 | Treasury yields macro inflation outlook | NO | **PASS** |
| C2 | NVDA earnings semiconductor AI revenue | NO | **PASS** |
| C3 | SSDI disability retirement income planning | NO | **PASS** |

**Perfect negative containment.** Hermes embeddings do not appear for unrelated queries. No personal/sensitive data leaked.

### D. Mixed Context

| Test | Query | Hermes Found | Result |
|------|-------|-------------|--------|
| D1 | SCHD dividend ETF income strategy analysis | NO | **PASS** |

Hermes FLYW/INFU content correctly absent from SCHD queries. Trade AI's own SCHD content not displaced.

---

## 4. Per-Embedding Rubric

### FLYW (id=26858)

| Criterion | Score (1-5) | Notes |
|-----------|-------------|-------|
| Direct retrieval | 4 | Found at rank 5 with 0.734 — good but not top |
| Semantic retrieval | 2 | Missed on alternative phrasing (B1) |
| Negative containment | 5 | Not found in any unrelated query |
| Provenance clarity | 5 | source_type='hermes_research', title includes phase |
| Content usefulness | 4 | Strong thesis challenge with evidence |
| RAG pollution risk | 5 (low) | Only appears for relevant queries |

**Overall: PASS_WITH_LIMITS** — strong for direct queries, weak for semantic alternatives

### INFU (id=26859)

| Criterion | Score (1-5) | Notes |
|-----------|-------------|-------|
| Direct retrieval | 5 | Rank 1 with 0.832 — excellent |
| Semantic retrieval | 3 | Found at rank 7 (0.505) — marginal |
| Negative containment | 5 | Not found in any unrelated query |
| Provenance clarity | 5 | source_type='hermes_research', title includes phase |
| Content usefulness | 4 | Good thesis challenge, hardened prompt quality |
| RAG pollution risk | 5 (low) | Only appears for relevant queries |

**Overall: PASS** — excellent direct retrieval, acceptable semantic

---

## 5. Key Findings

1. **Negative containment is perfect.** Hermes content never appears for unrelated queries. Zero RAG pollution risk at current scale.

2. **Direct retrieval works well.** Both embeddings found when queried by symbol + research type. INFU achieves rank 1.

3. **Semantic retrieval is limited.** The embedding text is primarily trade data (prices, PnL, exit reasons), not company descriptions. Alternative phrasings that describe the company rather than the trade don't match well.

4. **Provenance is clear.** source_type='hermes_research' distinguishes Hermes content from Trade AI content in every result.

5. **No over-matching.** Hermes content does not displace existing Trade AI results for unrelated queries.

---

## 6. Improvement Recommendations

| # | Improvement | Impact |
|---|------------|--------|
| 1 | Include company name/sector in embedding text | Would fix B1 (semantic relevance) |
| 2 | Include strategy_id in embedding title | Better context for retrieval |
| 3 | Consider RAG source_boost for hermes_research (currently default 1.0) | Could tune up or down |

---

## 7. Recommendations

| Decision | Recommendation | Reason |
|----------|---------------|--------|
| Rollback? | **NO** | Pilot is clean, no pollution, no over-matching |
| Expanded embeddings? | **YES (limited)** — embed remaining 5 rows | Retrieval quality proven, no pollution risk |
| Dashboard preview? | **YES (limited)** — read-only Hermes staged data display | Quality sufficient for advisory display |
| Production promotion? | **NO** — premature | Need more rows and operator review first |

---

## 8. Safety

| Item | Status |
|------|--------|
| New DB writes | **ZERO** |
| New embeddings | **ZERO** |
| content_embeddings writes | **ZERO** |
| Broker access | **ZERO** |
| Production mutations | **ZERO** |
| Cron/service changes | **ZERO** |

---

## 9. Next Recommended Gate

**Phase 2C — embed remaining 5 research rows + limited dashboard preview.**

Scope:
1. Embed remaining hermes_research_intelligence rows (ids 2, 3, 4, 6, 7) with improved embedding text (include symbol context)
2. Add read-only Hermes staged research display to Hermes Chat sidebar or a new Hermes Research panel
3. No production promotion
4. No autonomous cron
