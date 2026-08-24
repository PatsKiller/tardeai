# Librarian + curation maturity (PR C)

**Date:** 2026-08-23  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  
**Paid calls:** 0  
**Status:** **LIVE on CURRENT `bc6ff5c6`**. Merged as PR #492 (`6a3f4e0f` → `bc6ff5c6`). First natural post-merge tick **2026-08-24 00:23:52 ET**, run_id `62652d0c`, 117/2/1/0/120/0 paid. `TickerResearchState` reused; `HermesResearchContext@v2` asks WHAT_CHANGED. `hermes_curation_summary.jsonl` still empty (no material watermark change).

## Natural #489/#491 proof this PR starts from

systemd `tradeai-free-first-circulation.timer` LastTrigger **2026-08-23 22:24:15 ET**, CURRENT `3dd6f8d5`, run_id `433f8a56-3964-4812-80b0-b1d506ea96d2`, 117 Hermes / 2 RAG / 1 structured / 0 SearXNG / 120 FRESH_NO_CHANGE / 0 paid.

Second hourly tick **observed** 23:23:11–23:25:57 ET, run_id `6458ea63`, same 117/2/1/0/120/0 on `3dd6f8d5` (`R93_TWO_NATURAL_TICKS_PROVEN=true`). #492 merged after that PASS.

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

## POST-C natural proof (2026-08-24 00:23 ET)

systemd `tradeai-free-first-circulation.timer` LastTrigger **00:23:52 ET**, finished 00:26:51, PID 711753, CURRENT `bc6ff5c6`, run_id `62652d0c-7097-42c4-a1c6-8fc49315b2cf`.

- Graph / state / gaps / memory SHA256 unchanged vs 23:39 ET pre-tick snapshot.
- 120 `TickerResearchState` loaded; sample NOC/SCHG/PRSO/SOPAQ `context.question=WHAT_CHANGED`.
- `load_latest` curation = None (file absent). New curation versions = 0 by design of the NO_NEW_INFO write rule.
- 33 `ResearchGap@v1` rows (from post-merge baseline; 31 `all_stale`, 2 `unresolved_after_free` PRSO/VIVS) were **not** duplicated.
- Paid boundary: `paid_dispatch_entered=0`. Do not count legacy worker 429.

`R93_POST_C_NATURAL_PROVEN=true` for state reuse. Residual: persist an initial `HermesCurationSummary` on first review (even `NO_NEW_INFO`) is **not** in this PR and must not be silently patched on CURRENT. That is a future source change, not PR D.
