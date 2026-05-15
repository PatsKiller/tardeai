# Phase 2F — Global Shadow Retrieval Comparison

**Date:** 2026-05-14
**Status:** IN PROGRESS

## Purpose

Compare production nomic retrieval against full qwen3 shadow retrieval and hybrid merged retrieval across 100 production-style queries, without changing production routing.

## What Is Authorized

- Read-only comparison against content_embeddings (nomic) and content_embeddings_qwen3_shadow (qwen3)
- 100-query evaluation across 25 workflow categories
- Hybrid merged retrieval scoring
- Workflow-specific recommendations

## What Remains Blocked

- Global production RAG routing changes
- Replacing nomic-embed-text
- Phase 2G canary (pending these results)
- Phase 2H global promotion
