# R10.2 closeout (in progress)

**Date:** 2026-08-24  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

## Repository vs application

| | SHA |
|---|---|
| starting_main (R10 handoff) | `bc6ff5c6` (#492) |
| PR #493 exact head | `e4559ce3` docs-only POST-C |
| PR #493 merge / ending_main after docs | `631800ad` |
| application CURRENT | **`bc6ff5c6`** (not redeployed for docs) |
| pin_match (SOURCE/BUILD/GIT) | true on `bc6ff5c6` |

## Natural loop (baseline — do not re-prove)

117 Hermes / 2 RAG / 1 structured / 0 SearXNG / 120 FRESH_NO_CHANGE / 0 paid on the systemd timer. Additional same-pin fire 2026-08-24 **09:23:16 ET** run_id `b9b00556` exit 0, same shape.

## M1 status

Source on `feat/r10-m1-baseline-curation`. **Not live** until merge + exact-main CURRENT promote + `--project-baseline` + replay + a natural timer tick that loads `kind=BASELINE_PROJECTION` and still writes 0 material versions.

## PR D

Inventory only in this closeout generation. No producer disabled. Paid dispatch remains forbidden.

## Documentation drift (runtime wins)

| claim in older docs | measured now |
|---|---|
| PR C not started / NATURAL_PROOF_PENDING | superseded: two+ natural ticks, #492 live, #493 merged |
| CIO consumes TickerResearchState | **not wired** (architecture still honest) |
| ContextEnvelope is missing | **v1 exists**; v2 sections not universal |
| repo unit uses systemd flock | host ExecStart is bash wrapper, python fcntl only |
| main tip == CURRENT | after #493 **false by design** (`631800ad` vs `bc6ff5c6`) |
| hermes_curation_summary populated | **empty** until M1 live baseline |
| 78–82 / L6 LIVE | **program target**, not M1 claim |

## Remaining

M2–M5, PR D replacement proof, PR E UI, Postgres shadow, retrieval benchmarks, 200 golden cases. Do not claim 78–82 or L6 LIVE from M1 source alone.
