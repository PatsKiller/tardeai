

> **⚠️ Model policy (validated 2026-06-02):** gemma3:12b = primary chat, gemma3:4b = fallback, gemma3:27b = overnight; **qwen3-embedding:8b = embeddings (active)**; **qwen3:14b (chat) is DISABLED + uninstalled.** Any reference below to qwen3:14b as an active chat/generation model is superseded — see `MASTER_SYSTEM_DOCUMENTATION.md` §12.

---

# Appendix E — Initial Script Routing Matrix

Status:      ACTIVE
as_of:       2026-06-02T21:03:40-04:00
Measured at: efcc51365 / not measured

This matrix answers the operational question: “Which local-LLM scripts should use which model going forward?” It is an initial routing map, not permission to mass-refactor. Claude Code must validate it with the Phase 0 hardcoded-reference scan and live source inspection before changing any specific file.

## Core rule

Scripts should not name models directly. Scripts should declare a process type, and the existing config hub/wrapper should resolve the model from `.env`.

```python
from scripts.local_llm import execute
from scripts.llm_config import STANDARD  # or REALTIME / BATCH_OVERNIGHT / etc.

result = execute(prompt, process_type=STANDARD, script="script_name.py")
```

## Initial routing map

| Script / workflow | Process type | Model policy after rollout | Phase | Notes |
|---|---:|---|---:|---|
| `scripts/process_watchlist_agent_jobs.py` | STANDARD | `qwen3:14b` | Phase 0 | Main backend agent processor. Keep fast/local and compatible with active-hours operation. Do not move this wholesale to gemma3. |
| Maria / Steph / Risk backend analysis through shared job processor | STANDARD | `qwen3:14b` | Phase 0 | Existing two-pass and peer/RAG context path should stay on resident active-hours model unless later benchmark proves otherwise. |
| `scripts/incubator_llm_screener.py` | STANDARD | `qwen3:14b` | Phase 0 | Runs around premarket/evening; keep stable. Do not make it depend on gemma3 until pilot data exists. |
| `scripts/topic_curator.py` | STANDARD | `qwen3:14b` | Phase 0 | Daily curation and query improvement. Morning path should not trigger large-model GPU swaps. |
| `scripts/llm_intelligence_enrichment.py` | STANDARD | `qwen3:14b` | Phase 0 | Daily intelligence narratives. Keep stable during initial rollout. |
| `scripts/aegis_morning_brief_delivery.py` | STANDARD / REALTIME | `qwen3:14b` | Phase 0 | Morning operator-facing brief. Must remain reliable and quick. |
| `scripts/local_llm.py` | Execution path | no direct model; resolve from config | Phase 0 | Add audit/gating here only if this is confirmed as current execution path. |
| `scripts/local_llm_config.py` | Config hub | source of truth / extended hub | Phase 0 | Do not replace silently. New `llm_config.py`, if created, must wrap or extend this. |
| `scripts/multi_strategy_classifier.py` | BATCH_OVERNIGHT | `gemma3-overnight` after Phase 1 approval | Phase 1 pilot | First pilot candidate only. Must call `gate_batch_overnight()` or run under batch-window wrapper. |
| `scripts/strategy_weekly_review.py` | BATCH_OVERNIGHT | `gemma3-overnight` after Phase 1 approval | Phase 1 pilot | Second pilot candidate. Must restore/warm qwen before premarket. |
| `scripts/weekly_incubator_builder.py --llm` | BATCH_OVERNIGHT candidate | Candidate for `gemma3-overnight` after pilot passes | Later Phase 1 expansion | Do not change during initial pilot unless explicitly approved. |
| Overnight synthesis / long-form batch classifiers | BATCH_OVERNIGHT candidate | Candidate for `gemma3-overnight` | Later Phase 1 expansion | Group jobs behind one lifecycle wrapper where possible to avoid GPU thrash. |
| `scripts/rag_indexer.py` and embedding calls | EMBEDDING | `qwen3-embedding:8b` only after Phase 2 A/B pass | Phase 2 | `nomic-embed-text` remains default until retrieval-quality A/B passes and 48h observation is clean. |
| RAG retrieval query embedding helpers | EMBEDDING | `qwen3-embedding:8b` after Phase 2 | Phase 2 | Must never call cloud. |
| Report/document prose generation such as weekly/monthly summaries | MEDIA_CONTENT candidate | `gemma4:e4b` only after Phase 3 approval | Phase 3 pilot | Pilot one or two scripts first. Do not move all prose scripts at once. |
| YouTube/transcript summarization or article summarization workflows | MEDIA_CONTENT candidate | `gemma4:e4b` after Phase 3 pilot | Phase 3 | Keep qwen until coexistence and throughput tests pass. |
| Alex retirement, Roth, SSDI, IRMAA, complex tax decisions | CRITICAL_CLOUD | Cloud-only, fail loud | Existing/Phase 0 verified | No local fallback for critical retirement/tax decisions. Use live provider map from `.env`. |
| CIO synthesis or high-impact portfolio decisions | CRITICAL_CLOUD or cloud escalation | Cloud-required if policy says so | Existing/Phase 0 verified | Provider names must be discovered from live config. |
| Any direct `requests.post(...11434...)` Ollama caller found by grep | Migration list | no new direct calls; migrate gradually | Phase 0 inventory | Record in migration list. Do not mass-refactor in Phase 0. |

## What this does and does not do

This document does address the current local-LLM routing question, but it deliberately does it through a process-type migration pattern rather than hardcoding every script to a model. Phase 0 creates the live inventory and routing/audit layer. Phase 1 changes only pilot batch scripts. Phase 2 changes embeddings only after A/B retrieval validation. Phase 3 changes only pilot media/content scripts.

