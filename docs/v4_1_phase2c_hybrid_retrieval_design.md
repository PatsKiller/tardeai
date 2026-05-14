# Phase 2C: Hybrid Retrieval Design

**Version:** v4.1  
**Status:** DESIGN ONLY  
**Date:** 2026-05-14  
**Scope:** Dual-model retrieval with routing, merge, and deduplication  

---

## Phase 2C production routing is not authorized by this prompt.

---

## 1. Overview

Rather than a full cutover from nomic-embed-text to qwen3-embedding:8b, this design proposes a hybrid retrieval architecture where each model serves the query types it is best suited for. Results from both models are merged, deduplicated, and reranked.

---

## 2. Model Roles

| Model | Dimensions | Role | Query Types |
|-------|-----------|------|-------------|
| **nomic-embed-text** | 768 | Broad/default, high-volume, production baseline | News search, general RAG, card generation, screener context, real-time lookups |
| **qwen3-embedding:8b** | 4096 | High-value evidence, deep reasoning | Journal reviews, closed trade analysis, deep overnight synthesis, risk synthesis, proposal evidence gathering |

### Routing Rationale

- nomic-embed-text is fast, proven, and covers the high-volume surface area
- qwen3-embedding:8b provides richer semantic representation for complex, multi-faceted queries where retrieval quality directly impacts trade decisions
- Not all queries justify 4096-dimension cosine computation overhead

---

## 3. Routing Policy

### 3.1 Query Classification

Each retrieval request is tagged with a `query_context` that determines routing:

| Query Context | Route | Table |
|--------------|-------|-------|
| `news_lookup` | nomic only | `content_embeddings` |
| `screener_context` | nomic only | `content_embeddings` |
| `card_generation` | nomic only | `content_embeddings` |
| `general_rag` | nomic only | `content_embeddings` |
| `journal_review` | qwen3 primary, nomic fallback | `content_embeddings_qwen3` + `content_embeddings` |
| `closed_trade_analysis` | qwen3 primary, nomic fallback | `content_embeddings_qwen3` + `content_embeddings` |
| `deep_overnight` | qwen3 primary, nomic fallback | `content_embeddings_qwen3` + `content_embeddings` |
| `risk_synthesis` | qwen3 primary, nomic fallback | `content_embeddings_qwen3` + `content_embeddings` |
| `proposal_evidence` | qwen3 primary, nomic fallback | `content_embeddings_qwen3` + `content_embeddings` |

### 3.2 Default Behavior

- If `query_context` is not provided or unrecognized: route to nomic only
- If the qwen3 table does not exist or is empty: fall back to nomic silently
- If qwen3 embedding call fails (GPU down, model unloaded): fall back to nomic, log warning

---

## 4. Retrieval Pipeline

### 4.1 Single-Model Path (nomic only)

Current production behavior, unchanged:

1. Title ILIKE filter on query terms
2. Pull top 200 candidates
3. Python cosine similarity against query embedding (768d)
4. Apply recency decay + source boost
5. Return top N results

### 4.2 Hybrid Path (qwen3 primary + nomic)

```
Query
  |
  v
[Embed query with BOTH models in parallel]
  |                    |
  v                    v
[qwen3 table]      [nomic table]
  |                    |
  v                    v
Top N candidates    Top N candidates
(cosine 4096d)      (cosine 768d)
  |                    |
  +--------+-----------+
           |
           v
    [Merge + Dedupe]
           |
           v
    [Rerank by combined score]
           |
           v
    Return top N final results
```

### 4.3 Merge and Deduplication

1. Collect top N results from each model (N=20 default per model)
2. Deduplicate by `source_id` -- if a document appears in both result sets:
   - Normalize scores from each model to [0, 1] range within their respective result sets
   - Combined score = `(w_qwen3 * qwen3_score) + (w_nomic * nomic_score)`
   - Default weights: `w_qwen3 = 0.6`, `w_nomic = 0.4` (tunable)
3. Documents appearing in only one result set retain their normalized score, weighted by the respective model weight
4. Apply recency decay and source boost after merge (same logic as production)
5. Return top N final results (N=10 default)

### 4.4 Score Normalization

```python
def normalize_scores(results):
    """Min-max normalize cosine scores within a result set."""
    if not results:
        return results
    scores = [r['cosine_score'] for r in results]
    min_s, max_s = min(scores), max(scores)
    if max_s == min_s:
        for r in results:
            r['normalized_score'] = 1.0
    else:
        for r in results:
            r['normalized_score'] = (r['cosine_score'] - min_s) / (max_s - min_s)
    return results
```

---

## 5. Embedding the Query

For hybrid retrieval, the query must be embedded with both models:

```python
# Parallel embedding (can use asyncio or threading)
nomic_embedding = ollama.embeddings(model='nomic-embed-text', prompt=query_text)
qwen3_embedding = ollama.embeddings(model='qwen3-embedding:8b', prompt=query_text)
```

**Latency concern:** Two embedding calls instead of one. Mitigated by:
- Running in parallel (not sequential)
- nomic-embed-text is fast (~50-100ms)
- qwen3-embedding:8b is slower (~500ms-2s estimated) -- this is the bottleneck
- Total hybrid query latency dominated by the slower model

---

## 6. Fallback Policy

| Failure Mode | Behavior |
|-------------|----------|
| qwen3 model not loaded in Ollama | Fall back to nomic only, log warning |
| qwen3 table missing or empty | Fall back to nomic only, log warning |
| qwen3 embedding call timeout (>5s) | Fall back to nomic only, log timeout |
| qwen3 table has no results for query | Use nomic results only |
| nomic fails (should not happen in production) | Return error -- this is a critical failure |
| Both models fail | Return error, surface to operator |

All fallbacks are silent to the caller -- the retrieval function returns results regardless, with a `retrieval_meta` dict indicating which models were used.

---

## 7. Latency Risk

| Path | Estimated Latency |
|------|------------------|
| nomic only (current production) | 100-300ms |
| qwen3 only | 500ms-2s (GPU dependent) |
| Hybrid (parallel embed + dual search + merge) | 600ms-2.5s |

**Acceptable for:** Journal reviews, closed trade analysis, overnight synthesis, proposals (these are not real-time paths).

**Not acceptable for:** Real-time card generation, screener context, rapid news lookup -- these stay on nomic only.

---

## 8. Storage Risk

| Scenario | Estimated Storage |
|----------|------------------|
| Current production (14,784 rows x 768d, JSONB) | ~90 MB |
| Full qwen3 parallel index (14,784 rows x 4096d, JSONB) | ~480 MB |
| Both tables coexisting | ~570 MB |

This is manageable on local storage. Monitor with:

```sql
SELECT pg_size_pretty(pg_total_relation_size('content_embeddings')) AS nomic_size,
       pg_size_pretty(pg_total_relation_size('content_embeddings_qwen3')) AS qwen3_size;
```

---

## 9. Configuration

```python
HYBRID_RETRIEVAL_CONFIG = {
    'enabled': False,                    # Master switch -- off until Phase 2D promotion
    'qwen3_weight': 0.6,                # Weight for qwen3 scores in merge
    'nomic_weight': 0.4,                # Weight for nomic scores in merge
    'candidates_per_model': 20,          # Top N from each model before merge
    'final_top_n': 10,                   # Final results after merge
    'qwen3_timeout_ms': 5000,            # Timeout for qwen3 embedding call
    'qwen3_table': 'content_embeddings_qwen3',
    'nomic_table': 'content_embeddings',
    'hybrid_contexts': [                 # Query contexts that use hybrid retrieval
        'journal_review',
        'closed_trade_analysis',
        'deep_overnight',
        'risk_synthesis',
        'proposal_evidence',
    ],
}
```

---

## 10. Rollback

To revert to nomic-only retrieval:
1. Set `HYBRID_RETRIEVAL_CONFIG['enabled'] = False`
2. All queries route to nomic only
3. qwen3 table can remain or be dropped -- no impact on production
4. No code changes required beyond the config flag

---

## 11. Future Considerations

- If qwen3-embedding:8b proves significantly better, a full migration (Phase 2D) replaces the production table entirely
- If hybrid proves valuable long-term, consider pgvector for native cosine similarity at scale
- Weight tuning (w_qwen3, w_nomic) should be informed by Phase 2B A/B results
- Consider caching frequent query embeddings to reduce GPU load

---

## 12. Authorization Gate

```
# Phase 2C production routing is not authorized by this prompt.
# To enable hybrid retrieval in production, complete Phase 2D promotion checklist
# and issue operator command: "Enable Phase 2C hybrid retrieval routing"
```
