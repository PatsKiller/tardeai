# Librarian + curation maturity (PR C)

**Date:** 2026-08-23  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  
**Paid calls:** 0  
**Status:** source on `feat/r93-librarian-curation-maturity` — **not live** until merged, exact-main promoted, and naturally observed.

## Natural #489/#491 proof this PR starts from

systemd `tradeai-free-first-circulation.timer` LastTrigger **2026-08-23 22:24:15 ET**, CURRENT `3dd6f8d5`, run_id `433f8a56-3964-4812-80b0-b1d506ea96d2`, 117 Hermes / 2 RAG / 1 structured / 0 SearXNG / 120 FRESH_NO_CHANGE / 0 paid.

Second hourly tick (23:23 ET) is observed separately; PR C source does not wait on it to be authored.

## What PR C adds

| Object | Path | Role |
|---|---|---|
| HermesCurationSummary@v1 | `scripts/lib/hermes_curation_summary.py` | last material review; version only on material watermark change |
| TickerResearchState@v1 | extended | current knowledge projection + thesis_action |
| LibrarianAssessment@v1 | extended epistemic fields + `decision` |
| EvidenceFreshnessPolicy@v1 | class-specific TTLs (not one 7-day window) |
| ResearchGap@v1 | missing information, not LLM age |
| EvidenceContradiction@v1 | never silent overwrite |
| SecurityEvent@v1 | period-specific event GUIDs |
| HermesResearchContext@v2 | next iteration asks WHAT_CHANGED |

Deterministic. `FLASH_ELIGIBLE` may be marked by free-first; **execution is forbidden**.

## Version rule

No new curation version for: timestamp-only, same content hash, duplicate, embedding completion, health check, FRESH_NO_CHANGE, NO_NEW_INFO.

## Embedding

503 → ACQUIRED_EMBED_PENDING (from #489). Deferred embed reports `RAG_SEMANTIC_PENDING`, not NO_EVIDENCE.

## Not in this PR

PR D producer retirement. PR E CIO Ticker Intelligence UI. Paid provider activation. Postgres knowledge_* migration.

## PR D plan (inventory only — do not disable)

| Producer | Replacement | Gate |
|---|---|---|
| `tradeai-hermes-cio-worker --backend live` | FREE_FIRST_ONLY timer + Flash-on-delta later | PR C live + natural + explicit grant |
| crontab grok,chatgpt paired enhance/top20 | one OAuth challenger policy | after Flash lane proven |
| `hermes-autonomous-loop ticker_challenger` | same | failed today; do not start |
| rebuild `$PROJ` Hermes fleet | CURRENT pin | dual-root convergence |
| DeepSeek Pro bulk | exceptional only | never bulk |

Target hierarchy: L0 no LLM → L1 Flash material delta → L2 one OAuth challenger → L3 Pro exceptional. None activated here.
