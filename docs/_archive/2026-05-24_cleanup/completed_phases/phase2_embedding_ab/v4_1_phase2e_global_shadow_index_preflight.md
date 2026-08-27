# Phase 2E — Preflight Report

**Date:** 2026-05-14
**Status:** ALL GATES PASS

## Safety

| Gate | Result |
|------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Holdings guard | OK: $1,191,861 |
| Deep lock | None |
| Models installed | qwen3-embedding:8b, nomic-embed-text, qwen3:14b, gemma3-overnight |
| Production models resident | qwen3:14b + nomic-embed-text |

## Table Counts (pre-build)

| Table | Count |
|-------|-------|
| content_embeddings (production) | 14,872 |
| content_embeddings_qwen3_test | 4,897 |
| content_embeddings_qwen3_shadow | 0 (created this phase) |
