# Transferson canonical universe — local closeout

**Date:** 2026-08-25  
**Authority:** READ_ONLY_ADVISORY · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Branch:** `chore/transferson-canonical-universe` (local; not pushed)

## Where 120 came from

`data/cio/ticker_research_graph.jsonl` **TickerKnowledgeProfile@v1** rows, loaded by `free_first_refresh.load_profiles()`. Free-first `total_symbols` is that cohort. It is **graph-profiled circulation**, not the Transferson universe.

## Where 126 came from

**UNRESOLVED_WITH_REASON.** No code, live receipt, or current doc establishes 126 as a universe denominator. Forbidden as a count until lineage exists.

## 3,061

Historical **2026-08-22** `research_scheduler.load_universe()` split (22/30/331/141/2537) in `docs/RESEARCH_PRIORITIZATION.md`. Observation, not configuration. Requires DB `symbol_profiles` + proposals.

## What changed

- New `scripts/lib/transferson_universe.py` — `TransfersonUniverseManifest@v1`
- Membership reasons are a set; research tier is assigned separately
- WAIT/OVERSOLD stay in the universe (`REENTRY_HISTORY`) without becoming T1
- `research_scheduler.load_universe()` is now a **scheduler index** over the canonical manifest (READY/NEAR still T1; WAIT not in the scheduler index)
- Free-first still runs the graph-profile cohort and now labels `not_the_canonical_universe: true`
- Graph-profile count must be displayed as `N graph-profiled / M universe`

## Live validation (this host)

DB collectors returned empty. File-union canonical count = **120**, of which **120 graph-profiled**. That is **not** a declaration that the universe is 120; it is the file-derived union while `symbol_profiles` / proposals are unavailable in-process.

Scheduler index: 41 (holdings 19 + READY/NEAR 22). WAIT names in universe, not scheduler: 55.

## Tests

`tests/test_transferson_universe.py` + `tests/test_research_skip_gate.py` — 39 passed.

## Not in this tranche

- No LLM bulk research of cold names
- No R17 scan→checkpoint
- No deploy
- No remote push (new tranche; await operator sync)
