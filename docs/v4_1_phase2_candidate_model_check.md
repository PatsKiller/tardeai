# Phase 2A — Candidate Model Check

**Date:** 2026-05-14
**Candidate:** qwen3-embedding:8b
**Status:** INSTALLED and TESTED (2026-05-14)

---

## Model Inventory Check

```
ollama list | grep qwen3-embedding
qwen3-embedding:8b    64b933495768    4.7 GB    May 14 2026
```

## Current Production Model

- **nomic-embed-text:latest** — 274 MB disk, 0.54 GB VRAM resident
- Dimensions: 768
- Production since system inception
- All 14,000+ embeddings in `content_embeddings` use this model

## Candidate Model

- **qwen3-embedding:8b** — 4.7 GB disk, 5.67 GB VRAM when resident
- Confirmed dimensions: **4,096** (5.3x nomic's 768)
- Coexists with qwen3:14b (9.4 GB) — combined 15.07 GB, within 16 GB limit (~0.9 GB headroom)
- Evicts nomic-embed-text when both qwen models are resident
- Avg embedding latency: **295ms** (vs nomic's 23ms — 13x slower)
- EMBEDDING process type is local-only (never cloud, per LLM_FLEET_STRATEGY H4)

## Smoke Test Results (2026-05-14)

| Prompt | nomic dim | qwen3 dim | Both OK |
|--------|-----------|-----------|---------|
| "test embedding" | 768 | 4096 | YES |
| "RTX recovery watch evidence" | 768 | 4096 | YES |
| "closed trade review with MFE and MAE" | 768 | 4096 | YES |

## Pull Command

```bash
ollama pull qwen3-embedding:8b
```

## Expected Impact

- Local model download (several GB, one-time)
- May briefly affect Ollama bandwidth/availability during pull
- Does NOT change production embeddings
- Does NOT change production RAG routing
- Does NOT affect qwen3:14b or nomic-embed-text resident status

## Recommendation

Operator should approve the pull command when ready for A/B testing:

```
Approve pull qwen3-embedding:8b for Phase 2A embedding A/B testing.
```

After pull, the embedding_ab_baseline.py script can run candidate comparison.

## Phase 2A Without Candidate

Even without qwen3-embedding:8b installed:
- RAG/embedding discovery: COMPLETE
- Baseline tooling: CREATED (supports --no-candidate-ok)
- A/B query set: CREATED
- Design documents: CREATED
- Only candidate A/B comparison is blocked
