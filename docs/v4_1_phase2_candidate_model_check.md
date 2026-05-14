# Phase 2A — Candidate Model Check

**Date:** 2026-05-14
**Candidate:** qwen3-embedding:8b
**Status:** NOT INSTALLED

---

## Model Inventory Check

```
ollama list | grep qwen3-embedding
(no output — model not found)
```

## Current Production Model

- **nomic-embed-text:latest** — 274 MB disk, 0.54 GB VRAM resident
- Dimensions: 768
- Production since system inception
- All 14,000+ embeddings in `content_embeddings` use this model

## Candidate Model

- **qwen3-embedding:8b** — ~5 GB disk, ~5 GB VRAM estimated
- Expected dimensions: 4096 (Qwen3 embedding series)
- Would coexist with qwen3:14b (9.4 GB) — combined ~14.4 GB, within 16 GB VRAM limit with ~1.6 GB headroom
- EMBEDDING process type is local-only (never cloud, per LLM_FLEET_STRATEGY H4)

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
