# Yeda's Eye — first institutional-brain audit

**Date:** 2026-08-24  
**Authorized only after M1 natural PASS.**  
**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`

This cycle is an examiner report, not a feature dump. Production SQL `r10_memory_shadow.sql` was **not** applied. Neo4j was **not** installed.

## M1 natural evidence (LIVE)

systemd `tradeai-free-first-circulation.timer` LastTrigger **2026-08-24 11:23:44 EDT**, finished 11:27:13, PID 1126326, run_id `5e9028fb-00e1-4176-867e-fea55019ee90`, SOURCE `5c0a993a`, exit 0.

- 120 `BASELINE_PROJECTION` v0 loaded (JSONL SHA unchanged vs pre-tick)
- NOC/SCHD/SCHG/PRSO/CSCO/ANET: `WHAT_CHANGED`, not research-from-scratch
- Shape 117/2/1/0 SearXNG / 120 FRESH_NO_CHANGE / 0 paid
- New baseline rows 0, new MATERIAL versions 0, GUID forks 0
- Graph artifact count rose via RAG persist on circulate (1996 unique GUIDs) — not a curation version
- Watcher script HOLD was a **false negative** (`paid_dispatch_entered=0` treated as missing)

`R10_M1_LIVE_NATURALLY_PROVEN=true`

## Singleton

Python `fcntl` `LOCK_EX|LOCK_NB` in `free_first_refresh.py` is the cross-path singleton (CLI `--circulate`, `--project-baseline`, wrapper). systemd `Type=oneshot` serializes the unit. Host ExecStart has **no** systemd flock (double-flock caused exit 75). Repo unit file still wraps flock — **do not re-run installer**. Classify: **SINGLETON_PROVEN** for live host; **repo/host unit divergence** is P1 source hygiene, not a timer mutation.

## Memory topology (selected)

| store | rows | flag |
|---|---|---|
| hermes_curation_summary | 120 v0 BASELINE | LIVE |
| ticker_research_state | 120 | LIVE |
| ticker_research_graph | 120 profiles + 1996 arts | LIVE |
| aif_memory.jsonl | 345 | all RESEARCH_POINTER |
| CIO TickerResearchState readers | 0 live / **source PR #497** | SOURCE consumer (`cio_persistent_cognition`); live CURRENT still `5c0a993a` until merge+promote |
| cio_portfolio_theses.jsonl | 0 | ABSENT |
| operator_profile.jsonl | 0 | ABSENT |
| advisory_outcomes_v1.jsonl | 0 | ABSENT |

## M2 decisions

| question | answer |
|---|---|
| Postgres canonical now? | No. Isolated Docker `:55432` only. `production_applied=false` |
| Vector index | HNSW/IVFFlat **INDEX_CREATED** isolated; not architectural mandate |
| Neo4j | `POSTGRES_SUFFICIENT` |
| 200 golden cases | TESTED in-process (not live retrieval quality) |
| Storage decision | **POSTGRES_PGVECTOR** (pgmnemo v0.20.0 UNMEASURED_INSTALL) |

Do **not** apply `sql/r10_memory_shadow.sql` to production. Dual authoritative memory writers are forbidden.

### M2 isolated lanes (measured 2026-08-24)

| lane | substrate | status |
|---|---|---|
| A | native tstzrange bitemporal + DB-owned tx_time | MEASURED |
| B | native + pgvector 0.8.6 | MEASURED |
| C | pgmnemo current stable **v0.20.0** | MEASURED (lesson corpus; not MemoryFact@v2) |

Evaluate all three on: bitemporal correctness, point-in-time queries, RLS, concurrency, retrieval quality, HNSW, IVFFlat, exact retrieval, hybrid retrieval, backup/restore, operational complexity.

Corrected rules that remain in force (do not regress):

- NO mandatory Titan embedding
- NO mandatory HNSW
- NO automatic cosine→fact relationship
- NO universal timeline-continuity trigger
- NO SERIALIZABLE-everywhere
- NO fake hardware-isolation claim
- NO private chain-of-thought persistence
- NO fixed 10× over-fetch
- NO fixed 0.75 threshold without benchmark
- NO agent-only ratification of financial relationships

## Ranked debt

**P0** none from this natural tick (authority/paid/baseline intact).

**P1** Host vs repo flock unit file. CIO/Advisory consumption of `TickerResearchState` is **source PR #497** (not live until merge + exact-main + natural CIO cycle).

**P2** isolated Postgres / pgvector / pgmnemo shadow benchmark (after CIO consumption is naturally proven). AIF RESEARCH_POINTER cleanup.

**P3** Command Center Memory Brain.

## Next single PR

**Title:** feat(cio): consume persistent ticker cognition read-only (#497).  
**Reason:** persistence without consumption is not cognition.  
**Risk:** low if read-only, no producer retirement, no SQL apply.  
**Do not merge** under the authoring prompt. Operator review after exact-head CI.
