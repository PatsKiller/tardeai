# Phase 2E — Global Shadow Embedding Index

**Date:** 2026-05-14
**Status:** IN PROGRESS

## Purpose

Build a full qwen3-embedding:8b shadow index covering the entire production RAG corpus, without changing production RAG routing or replacing nomic-embed-text.

This is **shadow indexing, not promotion**. The output enables Phase 2F global shadow retrieval comparison.

## What Is Authorized

- Create content_embeddings_qwen3_shadow table
- Seed from existing qwen3 test table (4,897 rows)
- Backfill remaining ~10,000 production rows as qwen3 shadow embeddings
- Read production content_embeddings (read-only)
- Record coverage, latency, failures
- Restore qwen3:14b + nomic-embed-text after build

## What Remains Blocked

- Global production RAG routing changes
- Replacing nomic-embed-text as production embedding
- Using shadow table in production retrieval paths
- Phase 2F global shadow retrieval (after this phase)
- Phase 2H global production promotion

## Shadow Table

`content_embeddings_qwen3_shadow` — full-corpus qwen3-embedding:8b parallel index

## Next Phase

Phase 2F: Global shadow retrieval comparison (compare nomic vs qwen3 on full corpus without changing routing)
