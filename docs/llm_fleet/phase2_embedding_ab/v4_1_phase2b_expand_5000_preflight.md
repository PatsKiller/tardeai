# Phase 2B Expansion — Preflight Report

**Date:** 2026-05-14
**Status:** ALL GATES PASS

## Safety Gates

| Gate | Result |
|------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Holdings guard | OK: $1,187,937 |

## Model Inventory

| Model | Size | Status |
|-------|------|--------|
| qwen3-embedding:8b | 4.7 GB | Installed |
| nomic-embed-text | 274 MB | Installed, resident |
| qwen3:14b | 9.3 GB | Installed, resident |
| gemma3-overnight | 17 GB | Installed |
| gemma3:27b | 17 GB | Installed |

## Currently Resident (ollama ps)

- nomic-embed-text: 578 MB, 100% GPU, context 2048
- qwen3:14b: 10 GB, 100% GPU, context 4096

## Deep LLM Status

- Deep LLM lock: No lock file exists
- No active deep/gemma run detected

## Table Counts

| Table | Count |
|-------|-------|
| content_embeddings (production) | 14,796 |
| content_embeddings_qwen3_test | 1,000 |

## Git State

- Latest commit: 48cb178 (fix: trade journal data integrity + Alpaca reconciliation audit)
- Phase 2C commit: 431ab26

## Stop Conditions Checked

- [x] ALPACA_MODE is paper
- [x] LLM_DISABLE_LIVE_EXECUTION is true
- [x] Holdings > $1M
- [x] qwen3-embedding:8b installed
- [x] nomic-embed-text installed
- [x] qwen3:14b installed
- [x] content_embeddings_qwen3_test exists
- [x] Database available
- [x] No active deep/gemma run
- [x] No deep LLM lock
