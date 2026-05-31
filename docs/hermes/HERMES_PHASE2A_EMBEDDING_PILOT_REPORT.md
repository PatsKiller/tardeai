# Hermes Phase 2A — Embedding Architecture Pilot Report

**Date:** 2026-05-30
**Status:** COMPLETE

---

## Summary

First Hermes embedding pilot. Queued 2 research rows (FLYW id=1, INFU id=5), embedded via nomic-embed-text (768-dim, same as Trade AI), inserted into content_embeddings with source_type='hermes_research'. RAG retrieval confirmed: Hermes content found with score 0.741.

---

## Architecture

```
hermes_research_intelligence (staged rows)
    ↓ manually queued
hermes_embedding_queue (status=pending)
    ↓ hermes_embedding_worker.py
content_embeddings (source_type='hermes_research')
    ↓ rag_retrieval.py
RAG context (includes Hermes research alongside Trade AI content)
```

### Worker Script

`scripts/hermes_embedding_worker.py` — reads queue, embeds via Ollama nomic-embed-text, writes to content_embeddings, updates queue status. Supports `--dry-run` (default) and `--apply`.

---

## Pilot Results

| Item | Value |
|------|-------|
| Rows queued | 2 |
| Rows embedded | 2 |
| Embedding model | nomic-embed-text |
| Embedding dim | 768 |
| content_embeddings ids | 26858, 26859 |
| Queue status | both completed |

### Embedded Rows

| Queue ID | Research ID | Symbol | content_embeddings ID |
|----------|-------------|--------|-----------------------|
| 1 | 1 (FLYW) | FLYW | 26858 |
| 2 | 5 (INFU) | INFU | 26859 |

### RAG Retrieval Test

```
Query: "FLYW trade thesis challenge losses"
Total RAG results: 7
Hermes results: 1
  source_type=hermes_research
  title=FLYW — ticker_thesis_challenge (Hermes Phase 1E)
  rag_score=0.741
```

**Hermes content is discoverable via RAG at a competitive score (0.741).**

---

## Row Counts Before/After

| Table | Before | After | Change |
|-------|--------|-------|--------|
| hermes_research_intelligence | 7 | 7 | 0 |
| hermes_embedding_queue | 0 | **2** (completed) | +2 |
| content_embeddings (hermes_research) | 0 | **2** | +2 |
| content_embeddings (total) | ~25,979 | ~25,981 | +2 |

---

## Safety

| Item | Status |
|------|--------|
| Production table writes | **ZERO** (content_embeddings is append-only, not a mutation table) |
| Broker access | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades mutations | **ZERO** (38 unchanged) |
| Journal mutations | **ZERO** |
| Cron/service/daemon changes | **ZERO** |
| External APIs | **ZERO** |
| Embedding model | Same as Trade AI (nomic-embed-text, 768-dim) |

---

## Rollback

```bash
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) \
  psql -h localhost -U trade_ai -d trade_ai \
  -f docs/hermes/HERMES_PHASE2A_EMBEDDING_PILOT_ROLLBACK.sql
```

---

## Next Recommended Gates

| Gate | Status |
|------|--------|
| Embed remaining 5 research rows | NEEDS APPROVAL |
| Dashboard Hermes Challenger | NEEDS APPROVAL |
| Production promotion | NEEDS APPROVAL |
| Hermes autonomous research cron | NEEDS APPROVAL |
