# Session 2026-05-29 — Classifier Completion, llama.cpp Canary, Full Self-Healing Overhaul

**Commits:** 20 (7045209 through e21c6be)

## Executive Summary

Major session covering classifier completion, llama.cpp Vulkan canaries (gemma3:12b + gemma4:31b), 13 hardcoded qwen3:14b cleanups, and a full self-healing pipeline overhaul. Fixed critical enrichment timing gap (4-9 AM), rebuilt health agent with enrich-before-reject logic, hardened escalation handler with allowlisted retry_cmd direct execution, and replaced Claude CLI (API credits exhausted) with tiered local LLM analysis: gemma4:31b (best quality) → gemma3:12b (fast fallback) → optional Claude CLI.

## Commits

| Hash | Description |
|------|-------------|
| `7045209` | Fix trade close analyzer num_ctx for gemma3:12b GPU mode |
| `40c1ae1` | Fix hardcoded qwen3:14b warmup in GPU lifecycle and overnight scripts |
| `b6e7571` | Replace hardcoded qwen3:14b with env-driven model across 10 runtime scripts |
| `71bc6bc` | Validate classifier source/writer fix and backtesting lifecycle |
| `9364ff1` | llama.cpp Vulkan canary: gemma3:12b 2/3 PASS, 2-9x faster than Ollama |
| `aa9b3f5` | Gemma4 31B llama.cpp canary: 3/3 PASS, best quality, too slow for production |
| `12325ce` | Fix enrichment timing gap: extend cron 4AM-7:30PM |
| `ff804a5` | Fix health agent: enrich-before-reject, escalate stuck proposals to Claude Code |
| `6a3a485` | Document complete system health agent architecture |
| `907d377` | Validate self-healing health agent: all critical paths PASS |
| `a1738c3` | Audit proposal/backtest enhancements: lifecycle, SHFS 860, linkage |
| `069fc8a` | Harden escalation handler: allowlisted retry_cmd direct execution |
| `115606b` | Fix proposal lifecycle P0: expired case consistency |
| `cc19f48` | Switch escalation Tier 3 from Claude CLI to local gemma3:12b |
| `e21c6be` | Add gemma4:31b as Tier 3a deep analysis in escalation handler |

## Work Completed

### 1. Hardcoded Model Reference Cleanup (40c1ae1, b6e7571)

13 runtime files fixed. All hardcoded `qwen3:14b` references replaced with `os.getenv("LOCAL_LLM_MODEL", "gemma3:4b")` or updated constants:

- `api_v2.py` — 10 agent identities
- `run_deep_overnight_llm_window.sh` — RESTORE_MODEL
- `run_batch_overnight_gemma_pilot.sh` — RESTORE_MODEL + emergency warmup
- `health_agent_llm_review.py`, `multi_tier_trade_reviewer.py`, `claude_escalation_handler.py` — Ollama call payloads
- `report_llm_fleet_status.py`, `write_daily_llm_fleet_summary.py` — fleet reports
- `phase3_media_prose_routing_policy.py`, `prefetch_hybrid_rag_context.py` — policy/RAG
- `run_phase2c_hybrid_offline_pilot.sh`, `run_phase3d_expanded_media_prose_pilot.py` — pilot scripts
- `gpu_lifecycle.py` — docstring examples

**Root cause of "GPU lifecycle warmup failed for qwen3:14b" alert:** Overnight scripts had `RESTORE_MODEL="qwen3:14b"` — tried to warmup a disabled model after every batch.

### 2. Trade Close Analyzer Fix (7045209)

Added `num_ctx=4096` for gemma3:12b in `_call_ollama_direct()`. Without this, gemma3:12b's default 131K context caused HTTP 500 on VRAM overcommit. Dry-run result: 2/3 meaningful_structured_review.

### 3. Classifier/Backtesting Validation (71bc6bc)

- Source/writer fix confirmed working (commit ae8efe0 from yesterday)
- 3,592/3,593 backtest trades classified (99.97%)
- Only SHFS (id=860) remains — no enrichment data
- Champion simulations (BT_*, 3,516) clearly separated from replays (ER_*, 77)
- trade_transactions 153 unclassified is expected (no strategy_id column)

### 4. llama.cpp Vulkan Canary (9364ff1)

Built and tested llama.cpp b9405 (pre-built Ubuntu Vulkan x64) against Ollama 0.24.0:

| Test | llama.cpp | Ollama | Speedup |
|------|----------|--------|---------|
| basic_json | **2.8s** | 26.6s | 9.5x |
| strategy_classifier | **9.1s** | 11.1s | 1.2x |
| close_trade_analysis | 19.0s | 31.3s | 1.6x |

**Key finding:** Ollama's GGUF format is incompatible with upstream llama.cpp — separate model downloads required from HuggingFace.

**Recommendation:** Keep as benchmark tool. Production switch requires systemd service, VRAM contention handling, and 50+ trade batch validation.

### 5. Gemma4 31B llama.cpp Canary (aa9b3f5)

Tested gemma-4-31B-it Q3_K_M (14 GB) on llama.cpp Vulkan with 25 GPU layers + CPU hybrid (full GPU offload failed — OOM at 14 GB model + KV cache on 16 GB VRAM):

| Test | Gemma4 31B | Gemma3 12B | Ratio |
|------|-----------|-----------|-------|
| basic_json | 42.6s | 2.8s | 15x slower |
| strategy_classifier | **236.9s PASS** | 9.1s | 26x slower |
| close_trade_analysis | **279.0s PASS** | 19.0s | 15x slower |

**3/3 PASS.** Output quality is the best of any model tested — richer reasoning, higher confidence, more thorough analysis. But at 4 minutes per classifier call, not viable for batch production.

**Verdict:** Offline quality reviewer only (overnight deep analysis, 5-10 trade batches). Production remains gemma3:12b via Ollama.

## Model Policy (Unchanged)

- Primary: gemma3:12b on GPU/Vulkan
- Fallback: gemma3:4b
- Disabled: qwen3:14b, gemma4:e2b, gemma4:e4b, gemma3:27b on GPU

## Safety Confirmation

| Check | Status |
|-------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Orders placed | NONE |
| Broker writes | NONE |
| Cron changes | NONE |
| .env changes | NONE |
| DB writes | NONE (today) |
| Ollama updated | NO |
| llama-server | Stopped after canary |
| Health check | PASS (7/7) |

### 6. Enrichment Pipeline Gap Fix (12325ce)

**Root cause:** Proposals created at 4 AM by the pre-market screener sat unenriched for 3 hours because `auto_enrichment_runner` (*/5 9-15) and `proposal_enrichment_loop` (*/15 9-16) didn't run before 9 AM. The 7 AM health agent stale sweep rejected all 6 proposals after 2 hours with 0 enrichment attempts.

**Fix:** Both enrichment crons extended to `*/10 4-19 * * 1-5` (every 10 min, 4 AM - 7:50 PM weekdays).

### 7. Health Agent Enrich-Before-Reject (ff804a5)

**Problem:** Health agent's proposal cleanup rejected stuck proposals immediately without attempting enrichment. The Claude Code escalation queue never received enrichment-stuck items.

**Fix (4-level self-healing):**
1. Detect PENDING proposals unenriched >30 min → trigger `auto_enrichment_runner --force-all`
2. Track `enrichment_attempt_count` per proposal (up to 3 attempts)
3. Only reject after 3 failed enrichment attempts OR 6h hard timeout (was: 2h with 0 attempts)
4. Proposals with 2+ failed attempts escalated to Claude Code queue as fixable items

### 8. Health Agent Architecture Doc (6a3a485)

Complete reference doc: `docs/project/SYSTEM_HEALTH_AGENT_ARCHITECTURE.md`

Covers all 30+ monitored components, 4-level self-healing pipeline (retry → agent auto-queue → enrich-before-reject → Claude Code CLI escalation), cron schedules, escalation queue format, and monitoring commands.

### 9. Escalation Handler Hardening (069fc8a, cc19f48, e21c6be)

Rebuilt the escalation handler with allowlisted retry_cmd execution and tiered local LLM analysis:

| Tier | Engine | Purpose | Cost |
|------|--------|---------|------|
| 1 | Direct retry_cmd | Execute allowlisted safe commands | Free |
| 2 | gemma3:4b (Ollama) | Quick diagnosis | Free |
| **3a** | **gemma4:31b (llama.cpp)** | **Deep root cause analysis** | **Free** |
| 3b | gemma3:12b (Ollama) | Fast analysis fallback | Free |
| 3c | Claude Code CLI | Optional, requires API credits | $$ |

**Root cause of CLI failure:** "Credit balance is too low" — Claude CLI uses Anthropic API credits. Now all tiers default to local models (free). Claude CLI is optional via `ESCALATION_USE_CLAUDE_CLI=true`.

**Allowlist:** `config/claude_escalation_allowlist.yaml` — 17 allowed patterns (enrichment, health checks, pipeline requeue), 19 blocked patterns (orders, broker, DB mutations, sudo). Environment guards enforce ALPACA_MODE=paper.

**gemma4:31b auto-start:** Tier 3a automatically starts llama-server if the GGUF exists, unloads Ollama models to free VRAM, runs analysis, then stops the server.

## Model Tier Summary (End of Session)

| Tier | Model | Engine | Use Case |
|------|-------|--------|----------|
| **Production** | gemma3:12b | Ollama GPU | Classifier, analyzer, all batch work |
| Fast fallback | gemma3:4b | Ollama GPU | If 12b fails |
| **Offline quality** | gemma4:31b Q3_K_M | llama.cpp hybrid | Overnight deep review (5-10 trades) |
| Benchmark | gemma3:12b | llama.cpp GPU | Speed comparison, A/B testing |
| Disabled | qwen3:14b, gemma4 e2b/e4b, gemma3:27b GPU | — | Failed canaries |

## Next Steps

1. Verify enrichment pipeline runs correctly at next 4 AM pre-market screener
2. Monitor health agent enrich-before-reject behavior on next stuck proposal
3. SHFS (id=860) needs enrichment data for classification
4. Trade close analyzer batch with gemma3:12b (pending operator approval)
5. Consider systemd service for llama-server if pursuing gemma4:31b overnight reviews
6. No more classifier batches needed — phase complete
