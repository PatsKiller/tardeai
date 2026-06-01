# Hermes Phase 25A — Embedding Curator Dry-Run Design

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Candidate Pools

| Pool | IDs | Count | Notes |
|------|-----|-------|-------|
| Promoted but not embedded | 8, 10, 11 | 3 | FJSCX, APAM, TRX — promoted to cache but missing RAG |
| Staged source_discovery | 12, 13, 14, 15, 16 | 5 | SearXNG-sourced, have external URLs |
| Staged ticker_thesis (auto loop) | 17, 18 | 2 | ADBE, AGMH — from autonomous loop |
| Staged ticker_thesis (low conf) | 9 | 1 | TELO — conf 0.2, rejection candidate |
| Staged research_backlog | 19, 20, 21, 22, 23 | 5 | Research tasks, not research findings |
| Already embedded | 1–7 | 7 | Skip |

**Total pool: 16 candidates (excluding 7 already embedded)**

---

## Scoring Rubric (1–5)

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Evidence quality | HIGH | Substantive evidence in evidence_json |
| Source quality | HIGH | Credible source (SA, Yahoo, SEC, etc.) |
| Freshness | MEDIUM | Created/freshness within 30 days |
| Uniqueness | HIGH | Not duplicating existing embedded content |
| Retrieval usefulness | HIGH | Would improve RAG answers about this symbol |
| RAG pollution risk | HIGH (inverse) | Could mislead future queries? |
| Actionability support | MEDIUM | Supports operator decision-making |
| Duplication risk | HIGH (inverse) | Same content already in different embedding? |
| Operator value | MEDIUM | Operator would benefit from RAG surfacing this |
| Portfolio relevance | HIGH | Symbol is in current portfolio/watchlist |
| Income-gap relevance | MEDIUM | Supports income-rotation research |

---

## Rejection Criteria

A candidate is REJECTED if:
- confidence_score < 0.3 (too weak)
- research_type = 'research_backlog' (tasks, not findings — embedding a task is nonsensical)
- Already embedded (ids 1–7)
- Empty evidence_json AND empty summary
- Symbol not in portfolio or watchlist (low relevance)

---

## RAG Pollution Checks

Before recommending embedding:
1. Does the content add new information vs existing embeddings for this symbol?
2. Could the content mislead future queries (e.g., outdated price data)?
3. Is the source credible enough that RAG retrieval should surface it?
4. Is the content specific enough to avoid noise in unrelated queries?

---

## Future Pilot Cap

- Max 2 records recommended for embedding pilot
- Requires separate Phase 26 approval to actually embed
- Embedding uses existing nomic-embed-text 768-dim via Ollama
- Target: content_embeddings with source_type='hermes_research'

## Rollback for Future Pilot

```sql
-- Remove pilot embeddings
DELETE FROM content_embeddings
WHERE source_type = 'hermes_research'
  AND source_id IN (<pilot_ids>);

-- Remove from embedding queue
DELETE FROM hermes_embedding_queue
WHERE source_id IN (<pilot_ids>);
```
