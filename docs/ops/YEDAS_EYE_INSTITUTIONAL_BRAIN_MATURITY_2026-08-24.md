# Yeda's Eye — first institutional-brain audit

**Date:** 2026-08-24  
**Authorized only after M1 natural PASS.**  
**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`

This cycle is an examiner report, not a feature dump. Production SQL `r10_memory_shadow.sql` was **not** applied. Neo4j was **not** installed.

Do not rewrite historical timestamps below. R10.7 appends current state after the original M1 evidence.

## M1 natural evidence (LIVE) — historical

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

## Memory topology (selected) — R10.7

| store | rows | flag |
|---|---|---|
| hermes_curation_summary | 120 v0 BASELINE | LIVE |
| ticker_research_state | 120 | LIVE |
| ticker_research_graph | 120 profiles + RAG arts | LIVE |
| aif_memory.jsonl | 354 | 345 RESEARCH_REFERENCE, 5 PROCEDURAL_HINT, 4 OPERATOR_EXPLICIT_PREFERENCE |
| CIO TickerResearchState readers | live CURRENT `15ab2362` | DEPLOYED consumer (`cio_persistent_cognition`); pack-in-trace on material_scan **not** yet |
| cio_portfolio_theses.jsonl | 0 | ABSENT |
| operator_profile.jsonl | 0 | ABSENT |
| advisory_outcomes_v1.jsonl | 0 | ABSENT |

## M2 decisions (R10.7 close)

| question | answer |
|---|---|
| Postgres canonical now? | No. Isolated Docker `:55432` only. `production_applied=false` |
| Vector index | HNSW/IVFFlat **INDEX_CREATED** isolated; not architectural mandate |
| Neo4j | `POSTGRES_SUFFICIENT` |
| 200 golden cases | TESTED in-process (not live retrieval quality) |
| pgmnemo v0.20.0 | **MEASURED** isolated (ingest/BM25). Not MemoryFact@v2. **Not** UNMEASURED_INSTALL. **Not** DISQUALIFIED. |
| Storage decision | **POSTGRES_PGVECTOR** (`provisional=false`) because A/B/C are all MEASURED |
| Scale 10k | MEASURED |
| Scale 100k / 1M | **NOT_RUN** |

Do **not** apply `sql/r10_memory_shadow.sql` to production. Dual authoritative memory writers are forbidden.

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

## Maturity (do not claim 80+ because #498–#500 merged)

Separate: SOURCE · TESTED · MERGED · DEPLOYED · NATURALLY_PROVEN · BENCHMARKED · SHADOW · PRODUCTION.

| plane | before R10.7 | after R10.7 |
|---|---|---|
| CIO consumption | L3 source (#497) | L4 deployed; L5 blocked on pack-in-trace |
| bitemporal / M2 | L2/L3 isolated | L3 BENCHMARKED (three lanes MEASURED); SHADOW/PRODUCTION not started |
| semantic / M3 | L2 source | L3 source/test/merged/deployed; writer not live |
| cross-agent / M4 | L2/L3 source | L3 source/test/merged/deployed; L4 after natural same-brain on `15ab2362` |
| overall live | ~low 50s examiner | still not 80+ |

## Ranked debt

**P0** none from this cycle (authority/paid/baseline intact; production SQL unapplied).

**P1** 17 unresolved identities remain (3 CUSIP-like `NON_SECURITY_IDENTIFIER`, 14 `UNRESOLVED_WITH_REASON` including PRSO/REENTRY). Do not fabricate.

**P1** M2 production shadow schema is isolated-proven; production `:5432` apply waits on `production-sql-write` grant. Canonical JSONL remains authority.

**P2** 100k/1M scale; M2 production shadow-write/parity/rollback program; AIF RESEARCH_REFERENCE classification (no premature delete).

**P3** Command Center Memory Brain UI (PR E).

## Next

`M2_PRODUCTION_SHADOW_MIGRATION_DESIGN` is separately gated. Natural same-brain on CURRENT `15ab2362` is the remaining live proof, not another source PR.
