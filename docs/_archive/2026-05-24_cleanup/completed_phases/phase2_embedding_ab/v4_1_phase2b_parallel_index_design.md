# Phase 2B: Parallel Test Index Design

**Version:** v4.1  
**Status:** DESIGN ONLY  
**Date:** 2026-05-14  
**Scope:** Limited parallel embedding index for qwen3-embedding:8b A/B evaluation  

---

## Phase 2B apply is not authorized by this prompt.

---

## 1. Problem

The production `content_embeddings` table uses a unique constraint on `(source_type, source_id)`. This means a single row per document -- inserting a second embedding model for the same document would violate the constraint.

Three options were evaluated:

| Option | Approach | Risk | Recommendation |
|--------|----------|------|----------------|
| **A** | New table `content_embeddings_qwen3_test` | Lowest -- no schema changes to production | **Recommended** |
| **B** | ALTER unique constraint to `(source_type, source_id, embedding_model)` | Medium -- alters production schema, all queries must be aware of model column | Not recommended for test phase |
| **C** | Temporary table `tmp_phase2_embedding_ab` | Low risk but semantically unclear, may be dropped by maintenance scripts | Not recommended |

**Decision: Option A -- separate test table.**

Rationale:
- Zero risk to production retrieval pipeline
- Clean rollback (DROP TABLE)
- No ALTER on a 14,784-row production table during active trading hours
- Test queries can join or union as needed without modifying existing code paths

---

## 2. Table Schema

```sql
CREATE TABLE content_embeddings_qwen3_test (
    id              SERIAL PRIMARY KEY,
    source_type     TEXT NOT NULL,
    source_id       INTEGER NOT NULL,
    title           TEXT,
    tfidf_terms     TEXT,
    top_keywords    TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    embedding       JSONB NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'qwen3-embedding:8b',
    embedding_dim   INTEGER NOT NULL DEFAULT 4096,

    CONSTRAINT uq_qwen3_test_source UNIQUE (source_type, source_id)
);

CREATE INDEX idx_qwen3_test_source_type ON content_embeddings_qwen3_test (source_type);
CREATE INDEX idx_qwen3_test_created_at ON content_embeddings_qwen3_test (created_at);
```

Notes:
- Schema mirrors `content_embeddings` exactly, with `embedding_dim` defaulting to 4096
- `embedding_model` is hardcoded to `qwen3-embedding:8b` for this test table
- JSONB embedding column (no pgvector) -- Python-side cosine similarity, consistent with production

---

## 3. Sample Population

**Target: 500-2000 documents** from high-value, recent source types.

| Source Type | Target Count | Selection Criteria |
|-------------|-------------|-------------------|
| `news` | 400-800 | Most recent by `created_at` |
| `agent_result` | 100-300 | Most recent by `created_at` |
| `youtube` | 50-150 | Most recent by `created_at` |
| `decision_outcome` | 50-200 | Most recent by `created_at` |
| `trade_review` | 50-200 | Most recent by `created_at` |

Selection query pattern:
```sql
SELECT source_type, source_id, title, tfidf_terms, top_keywords
FROM content_embeddings
WHERE source_type IN ('news', 'agent_result', 'youtube', 'decision_outcome', 'trade_review')
ORDER BY created_at DESC
LIMIT 2000;
```

Each selected document will be re-embedded using `qwen3-embedding:8b` via the local Ollama GPU pipeline and inserted into the test table.

---

## 4. Embedding Pipeline

1. Query production `content_embeddings` for the sample set (title + tfidf_terms as input text)
2. For each document, call `ollama.embeddings(model='qwen3-embedding:8b', prompt=text)`
3. Validate output dimension = 4096
4. Insert into `content_embeddings_qwen3_test`
5. Log: source_type, source_id, embedding_dim, latency_ms, success/failure

**Rate limiting:** Batch size 10, respect GPU queue / toll gate if active.

**Estimated time:** At ~15s/chunk on Arc B580, 2000 docs = ~8-9 hours. Run overnight.

---

## 5. Validation Queries

After population, verify:

```sql
-- Row count
SELECT COUNT(*) FROM content_embeddings_qwen3_test;

-- Source type distribution
SELECT source_type, COUNT(*) FROM content_embeddings_qwen3_test GROUP BY source_type;

-- Dimension consistency
SELECT DISTINCT embedding_dim FROM content_embeddings_qwen3_test;

-- Embedding array length check (sample)
SELECT source_type, source_id, jsonb_array_length(embedding) AS dim
FROM content_embeddings_qwen3_test
LIMIT 10;

-- Null/empty embedding check
SELECT COUNT(*) FROM content_embeddings_qwen3_test
WHERE embedding IS NULL OR embedding = '[]'::jsonb;
```

---

## 6. A/B Comparison Framework

For a set of test queries (sourced from recent proposal prompts, journal questions, risk synthesis inputs):

1. Run retrieval against production `content_embeddings` (nomic-embed-text, 768d)
2. Run identical retrieval against `content_embeddings_qwen3_test` (qwen3-embedding:8b, 4096d)
3. Compare: top-10 overlap, cosine score distribution, relevance rating (manual spot-check)
4. Record results in a comparison log for Phase 2D promotion decision

---

## 7. Rollback

```sql
DROP TABLE IF EXISTS content_embeddings_qwen3_test;
```

No production impact. No schema changes to revert. No index rebuilds required.

---

## 8. Storage Estimate

- 2000 rows x 4096 dimensions x ~8 bytes/float in JSONB = ~65 MB for embeddings alone
- With metadata overhead: ~70-80 MB total
- Production table (14,784 rows x 768d): ~90 MB estimated
- Full migration (14,784 rows x 4096d): ~480 MB estimated

---

## 9. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| GPU contention during overnight embedding run | Schedule after market close, respect toll gate queue |
| qwen3-embedding:8b model not yet pulled | Verify `ollama list` includes model before starting |
| Embedding dimension mismatch | Validate every output dimension = 4096 before insert |
| Test table persists and causes confusion | Document in A1A; add comment to table; clean up after Phase 2D decision |

---

## 10. Phase 2B Apply Command Placeholder

```
# Phase 2B apply is not authorized by this prompt.
# To execute Phase 2B, issue a separate operator command:
#   "Begin Phase 2B parallel index build"
```
