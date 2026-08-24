# R10 memory architecture correction closeout

**Date:** 2026-08-24  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

## STARTING_STATE

| | |
|---|---|
| protected_main | `631800ad` (#493) |
| application CURRENT | `bc6ff5c6` pin_match true |
| PR #494 | OPEN MERGE_CANDIDATE `a14bebad` CI 4/4 green — **not merged** (no operator merge grant) |
| free-first | LastTrigger 09:23:16 ET run_id `b9b00556` 117/2/1/0/120/0 paid 0 |

## Defects

| # | decision | status |
|---|---|---|
| 1 Titan vs local-first | LOCAL_ONLY; Titan disabled | TESTED |
| 2 Neo4j mandate | not installed; INSUFFICIENT_DATA | DESIGNED |
| 3 HNSW mandate | INSUFFICIENT_DATA | TESTED harness |
| 4 cosine⇒RELATED_TO | SimilarityCandidate cannot self-ratify | TESTED |
| 5 hardware isolation | logical tenant filter; fail closed | TESTED |
| 6 persist CoT | DecisionRationale only | TESTED |

## GPU audit (do not uninstall)

Installed: gemma3:{4,12,12b-ctx4k,27b,overnight}, qwen3:8b, qwen3-embedding:8b, nomic-embed-text:latest.

Runtime at 10:13 ET: `ollama serve` + runner **gemma3:12b** (GENERATIVE_ACTIVE, Stopping). Embedding-only is the only allowed memory-path model (`nomic-embed-text`, digest matches policy). Uninstall authorized: **NO**.

## Maturity (honest)

overall institutional memory remains **L1/L2 source** for bitemporal/tenant/similarity. Live research autonomy stays the proven free-first loop (**L5 natural repeated** on CURRENT `bc6ff5c6`). Do not average source into live 65/100.
