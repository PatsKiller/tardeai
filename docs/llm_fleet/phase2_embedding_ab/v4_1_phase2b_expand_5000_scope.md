# Phase 2B Expansion — 5,000 Document Scope

**Date:** 2026-05-14
**Phase:** 2B-Expanded
**Status:** IN PROGRESS

## Why 1,000 Documents Was Insufficient

The initial Phase 2B parallel index built 1,000 qwen3-embedding:8b test embeddings. Phase 2C hybrid retrieval found:

- **2.5% consensus** between nomic and qwen3 — both models rarely agreed on the same documents
- **5 of 14 source types** covered — qwen3 had zero coverage for news (0.24%), social_post (0%), decision_outcome (0%), youtube (0%), agent_synthesis (0%), cio_decision (0%), sec_form4 (0%)
- **Low consensus was a coverage artifact**, not a model quality issue — qwen3 cannot return documents it hasn't indexed

The Phase 2C evaluation explicitly recommended: "Expand qwen3 index to 5,000+ documents before drawing conclusions about hybrid retrieval value."

## Why 5,000 Documents Is the Next Safe Test Size

- **Coverage**: 5,000 docs covers ~34% of production (14,796 rows), versus 6.8% at 1,000
- **Source diversity**: Balanced sampling ensures all 13 source types are represented
- **Build time**: ~20 minutes (3,897 new docs × ~300ms/embedding)
- **VRAM**: qwen3-embedding:8b (4.7 GB) fits alongside qwen3:14b (9.3 GB) on Intel Arc B50
- **Reversible**: Test table only — production embeddings unchanged

## Safety Constraints

| Constraint | Status |
|-----------|--------|
| Production content_embeddings changed | **NO** |
| Production RAG routing changed | **NO** |
| Cron changed | **NO** |
| .env changed | **NO** |
| Broker/holdings/execution changed | **NO** |
| Phase 2D promotion blocked | **YES** — requires explicit operator approval |
| A1A documentation protocol | **ACTIVE** |
