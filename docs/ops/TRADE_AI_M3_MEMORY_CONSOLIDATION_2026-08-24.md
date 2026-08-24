# M3 memory consolidation (source)

**Date:** 2026-08-24  
**Status:** SOURCE + TESTED. Not MERGED. Not LIVE. Not NATURALLY_PROVEN.  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

Production writer cutover is **not** authorized by this PR.

## Contracts

- `AgentEpisode@v1` — GUID-referenced office events
- `MemoryConsolidator@v1` — admit CANDIDATE facts after dedupe / injection / quarantine
- `PreferenceCandidate@v1` — repeated feedback; operator confirmation still has `policy_effect=false`
- `SemanticOperatorMemory@v1` — planes separated from RAG prose
- `LessonCandidate@v1` — outcomes do not become methodology at n=1

## Flow

episode → atomic candidate → entity GUID → dedupe → temporal compare → contradiction → TTL → injection scan → admission.

## Storage

M2 decision (sibling PR): **POSTGRES_PGVECTOR**. This PR does not apply SQL.
