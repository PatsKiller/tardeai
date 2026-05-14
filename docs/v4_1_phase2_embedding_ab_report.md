# Phase 2A — Embedding A/B Baseline Report

**Date:** 2026-05-14
**Status:** Baseline complete, candidate NOT TESTED (not installed)

---

## Summary

| Metric | Baseline (nomic-embed-text) | Candidate (qwen3-embedding:8b) |
|--------|---------------------------|-------------------------------|
| Available | YES | NOT INSTALLED |
| Dimensions | 768 | ~4096 (expected) |
| Avg latency | 23ms | N/A |
| Empty results | 0/40 | N/A |
| Source diversity (top-5) | 5 types | N/A |
| Docs sampled | 1,000 | N/A |
| Queries tested | 40 | 0 |

## Production Impact

- **No production embeddings changed:** TRUE
- **No production RAG routing changed:** TRUE
- **No cron changed:** TRUE
- **No .env changed:** TRUE
- **No broker/holdings/execution changed:** TRUE

## Candidate Status

qwen3-embedding:8b is **NOT INSTALLED**. To proceed with A/B comparison:

```bash
ollama pull qwen3-embedding:8b
```

Expected: ~5 GB download, ~5 GB VRAM when resident. Coexists with qwen3:14b within 16 GB limit.

## Baseline Results

nomic-embed-text performs reliably:
- 0% empty result rate across 40 diverse queries
- 23ms average embedding latency (fast)
- 5 source types represented in top-5 results
- Source distribution: agent_result (573), fused_signal (402), news (8), trade_review (11), trade_outcome (6)

## Verdict

**NOT TESTED** — Candidate model is not installed.

## Phase 2B Recommendation

**HOLD** — Cannot recommend Phase 2B parallel index without candidate A/B data. Operator should:
1. Approve `ollama pull qwen3-embedding:8b`
2. Re-run A/B baseline with candidate
3. Compare retrieval quality before proceeding to Phase 2B

## Phase 2D Promotion Status

**BLOCKED** — Production embedding promotion requires separate operator command:

> Begin Phase 2D production embedding promotion.
