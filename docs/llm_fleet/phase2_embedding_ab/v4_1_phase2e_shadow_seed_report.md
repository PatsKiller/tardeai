# Phase 2E — Shadow Seed Report

**Date:** 2026-05-14

## Seed Operation

Copied compatible embeddings from `content_embeddings_qwen3_test` to `content_embeddings_qwen3_shadow`.

| Metric | Value |
|--------|-------|
| Source (qwen3 test) | 4,897 rows |
| Copied | 4,897 |
| Skipped (duplicate) | 0 |
| Incompatible | 0 |
| Shadow after seed | 4,897 |

## Source Mix (seeded)

| Source Type | Count |
|-------------|-------|
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

## Production Impact

None. Production `content_embeddings` read-only.
