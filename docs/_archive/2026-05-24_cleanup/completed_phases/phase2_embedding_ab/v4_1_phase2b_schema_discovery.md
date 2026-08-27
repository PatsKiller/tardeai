# Phase 2B — Schema Discovery

**Date:** 2026-05-14

## Production Table: content_embeddings

| Column | Type | Notes |
|--------|------|-------|
| id | bigint (serial) | PK |
| source_type | text | NOT NULL |
| source_id | bigint | NOT NULL |
| title | text | Content preview (~300 chars) |
| tfidf_terms | jsonb | TF-IDF weights |
| top_keywords | text[] | Extracted keywords |
| created_at | timestamptz | Embedding creation time |
| embedding | jsonb | 768-dim float vector as JSON array |
| embedding_model | text | DEFAULT 'nomic-embed-text' |
| embedding_dim | integer | DEFAULT 0 |

### Constraints
- PK: id
- UNIQUE: (source_type, source_id)

### Indexes
- btree PK on id
- btree UNIQUE on (source_type, source_id)
- GIN on top_keywords
- btree on (source_type, source_id)

### Key Facts
- **No pgvector** — embeddings stored as jsonb, similarity computed in Python
- **14,787 rows** across 14 source types
- **768 dimensions** (nomic-embed-text)
- **UNIQUE constraint prevents multi-model in same table** — (source_type, source_id) allows only one embedding per doc

## Decision: Separate Parallel Table

Because:
1. No pgvector means no native vector operations regardless
2. UNIQUE(source_type, source_id) prevents storing both 768d and 4096d for same doc
3. Dimension mismatch (768 vs 4096) would break any cosine comparison in same table
4. Separate table is cleanest rollback: DROP TABLE

### Parallel Table: content_embeddings_qwen3_test

Same structural pattern as production but with:
- 4096 dimensions (qwen3-embedding:8b)
- Latency tracking per embedding
- Content preview stored for debugging
- UNIQUE on (source_type, source_id, embedding_model) for safety
