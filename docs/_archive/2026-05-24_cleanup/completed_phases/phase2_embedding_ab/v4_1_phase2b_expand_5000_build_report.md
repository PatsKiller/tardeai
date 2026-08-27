# Phase 2B Expansion — Build Report

**Date:** 2026-05-14

## Build Summary

| Metric | Value |
|--------|-------|
| Starting qwen3 row count | 1,000 |
| Ending qwen3 row count | 4,897 |
| Rows added | 3,897 |
| Source types covered | 13 of 14 |
| Runtime | 1,066s (~18 min) |
| Average embedding latency | 267.9ms |
| Failed | 0 |
| Skipped (no title) | 0 |
| Skipped (duplicate) | 1,000 (existing rows preserved) |
| GPU model | Intel Arc B50 (Vulkan) |
| Embedding model | qwen3-embedding:8b (4.7 GB) |

## Source Mix

| Source | Count |
|--------|-------|
| agent_result | 1,500 |
| fused_signal | 900 |
| news | 600 |
| decision_outcome | 500 |
| cio_decision | 400 |
| agent_synthesis | 400 |
| youtube | 250 |
| social_post | 200 |
| sec_form4 | 100 |
| fred_series | 28 |
| trade_review | 11 |
| trade_outcome | 7 |
| brave_cache | 1 |

## Model Lifecycle

- qwen3-embedding:8b loaded for build
- qwen3-embedding:8b unloaded after build
- nomic-embed-text restored to resident after build
- qwen3:14b remained resident throughout

## Production Impact

None. Only content_embeddings_qwen3_test was modified.
