# Phase 2E — Shadow Schema Report

**Date:** 2026-05-14

## Table

`content_embeddings_qwen3_shadow`

## Schema

Aligned with `content_embeddings_qwen3_test`:

| Column | Type | Notes |
|--------|------|-------|
| id | BIGSERIAL PK | Auto-increment |
| source_type | TEXT NOT NULL | e.g., agent_result, news |
| source_id | BIGINT NOT NULL | Links to source table |
| title | TEXT | Embedding text source |
| content_preview | TEXT | First 200 chars |
| content_hash | TEXT NOT NULL | SHA256 prefix |
| embedding | JSONB | 4096-dim vector |
| embedding_model | TEXT NOT NULL | 'qwen3-embedding:8b' |
| embedding_dim | INTEGER NOT NULL | 4096 |
| embedding_latency_ms | REAL | Per-doc latency |
| source_created_at | TIMESTAMPTZ | Original creation time |
| indexed_at | TIMESTAMPTZ | When shadow was created |

## Constraints

- UNIQUE(source_type, source_id, embedding_model)

## Indexes

- source_type, source_id (composite)
- embedding_model
- source_type
- indexed_at

## Storage

Embeddings stored as JSONB (same as production and test tables). No pgvector extension used.

## Production Impact

None. Production `content_embeddings` table is unchanged.

## Rollback

```sql
DROP TABLE IF EXISTS content_embeddings_qwen3_shadow;
```
