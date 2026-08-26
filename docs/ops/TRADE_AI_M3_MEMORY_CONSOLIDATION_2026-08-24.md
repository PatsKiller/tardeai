# M3 memory consolidation

**Date:** 2026-08-24  
**Status:** SOURCE + TESTED + MERGED (#499 `61d05ca3`, reconciled head `beb83a53`) + DEPLOYED on exact-main `15ab2362`. **Not a production writer cutover. Not NATURALLY_PROVEN as a writer.**  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

Production writer cutover is **not** authorized. No dual writer. No inferred operator statement becomes investment policy, risk limit, execution permission, or permanent preference.

## Contracts (present on exact-main)

- `AgentEpisode@v1` — GUID-referenced office events
- `MemoryConsolidator@v1` — admit CANDIDATE facts after dedupe / injection / quarantine
- `PreferenceCandidate@v1` — repeated feedback; operator confirmation still has `policy_effect=false`
- `SemanticOperatorMemory@v1` — planes separated from RAG prose
- `LessonCandidate` linkage — outcomes do not become methodology at n=1

## Flow

`AgentEpisode` → candidate fact → entity resolution (`security_guid` spine; ticker is alias) → dedupe → temporal comparison → contradiction detection → TTL/retention → injection scan → `MemoryCandidate`.

Preference lifecycle: OBSERVATION → PreferenceCandidate → corroboration → optional operator confirmation → semantic memory → policy **only** through a separately governed policy process.

## Tests (source)

Episode idempotency, duplicate feedback (DEDUPE), injection quarantine, preference supersession with `policy_effect=false`, one-off outcome ≠ lesson, one-off statement ≠ policy, research prose classified as `RESEARCH_POINTER`.

## RESEARCH_POINTER classification plan (do not delete history)

Live `data/cio/aif_memory.jsonl` (354 rows as of 2026-08-24 20:10 ET):

| memory_type | n | destination |
|---|---|---|
| RESEARCH_REFERENCE | 345 | Hermes/RAG/evidence graph — **not** semantic operator memory |
| PROCEDURAL_HINT | 5 | keep as operator-context candidate; TTL |
| OPERATOR_EXPLICIT_PREFERENCE | 4 | PreferenceCandidate path; still `policy_effect=false` |

Do **not** delete RESEARCH_REFERENCE rows in this program. Later migration: classify in place, copy stable operator context into `SemanticOperatorMemory@v1`, leave research prose as pointers (`source_refs`) into Hermes/RAG. Semantic operator memory should hold: stable operator context, preferences, confirmed constraints, durable lessons — not copied research prose.

## Storage

M2 winner **POSTGRES_PGVECTOR** is the architectural substrate. This PR does not apply SQL.
