# Hermes Phase 7F — Ollama/Hermes Model Safety Reconciliation

**Date:** 2026-05-31
**Status:** PASS

---

## Ollama Inventory

| Model | Size | Status |
|-------|------|--------|
| gemma3:12b | 7.6GB | Hermes primary — available |
| gemma3:4b | 3.1GB | Trade AI default, Hermes fallback — available |
| gemma3:27b | 16.2GB | Not production — available |
| gemma3-overnight | 16.2GB | Deep overnight alias — available |
| nomic-embed-text | 0.3GB | Embedding model — available |
| qwen3-embedding:8b | 4.4GB | Hybrid RAG (offline) — available |

## Resident Models

**None loaded** at time of audit. Models load on demand and unload after `OLLAMA_KEEP_ALIVE=5m`.

## Hermes Model Configuration

| Setting | Value | Status |
|---------|-------|--------|
| Hermes default model | gemma3:12b | CORRECT |
| Provider | custom (Ollama) | CORRECT |
| Base URL | http://127.0.0.1:11434/v1 | CORRECT |
| External models | NONE | CORRECT |
| Grok/xAI | NOT CONFIGURED | CORRECT |
| Cloud fallback | NOT ACTIVE | CORRECT |

## Ollama Global Settings

| Setting | Value | Impact |
|---------|-------|--------|
| OLLAMA_KEEP_ALIVE | 5m (from zz-tradeai-llm-safety.conf) | Model unloads 5 min after last use — SAFE |
| OLLAMA_MAX_LOADED_MODELS | 1 | Only 1 model resident at a time — SAFE |
| OLLAMA_NUM_PARALLEL | 1 | No concurrent requests — SAFE |
| OLLAMA_VULKAN | 1 | GPU acceleration — OK |
| OLLAMA_NUM_GPU | -1 | All layers on GPU — OK |
| OLLAMA_HOST | 0.0.0.0:11434 | Accessible via Tailscale — OK |

**Note:** `override.conf` has `OLLAMA_KEEP_ALIVE=-1` (infinite) but `zz-tradeai-llm-safety.conf` loads last and overrides to 5m. Effective keep_alive is **5 minutes**.

## VRAM/Co-Residency Assessment

| Scenario | Risk |
|----------|------|
| Hermes (gemma3:12b) + Trade AI (gemma3:4b) | LOW — MAX_LOADED_MODELS=1 prevents co-residency |
| Hermes 01:00 UTC vs overnight deep (gemma3-overnight) | LOW — overnight runs at 23:00 ET, Hermes at 01:00 UTC (9 PM ET) — 2-hour gap |
| Hermes vs embedding (nomic-embed-text) | LOW — different model, auto-swap via MAX_LOADED_MODELS=1 |

**No VRAM pressure risk.** Only 1 model loaded at a time. Hermes loads gemma3:12b, uses it, and it unloads after 5 minutes.

## Hermes Autonomous Loop Model Behavior

- Loop calls Ollama `/api/chat` with `model=gemma3:12b`
- No explicit `keep_alive` parameter sent — uses global 5m default
- No explicit unload command — relies on OLLAMA_KEEP_ALIVE timeout
- **SAFE:** Model auto-unloads 5 minutes after Hermes loop completes

## num_ctx Assessment

- Hermes autonomous loop uses `num_ctx=8192` in chat calls
- Hermes gateway browse proxy uses `num_ctx=8192`
- gemma3:12b supports up to 131,072 native
- Ollama default runtime is 2048 unless overridden per-request
- **Current 8192 is sufficient** for staged research tasks
- 65536 would be useful for longer context but not required now

## Deep Overnight Conflict Check

| Timer | Schedule | Model | Conflict? |
|-------|----------|-------|-----------|
| Hermes autonomous | 01:00 UTC (9 PM ET) | gemma3:12b | NO |
| Deep overnight queue | 03:00 UTC (11 PM ET) | gemma3-overnight/12b | NO — 2h gap, auto-unload |

## Findings

| Check | Result |
|-------|--------|
| Hermes uses local model | PASS |
| No external/cloud models | PASS |
| No Grok/xAI | PASS |
| keep_alive safe | PASS (5m auto-unload) |
| VRAM co-residency safe | PASS (MAX_LOADED_MODELS=1) |
| Overnight conflict | PASS (2h gap) |
| num_ctx adequate | PASS (8192 sufficient) |
| No .env changes needed | PASS |
| No service changes needed | PASS |
| No model routing changes needed | PASS |

## Required Changes

**NONE.** Current configuration is safe and aligned with LLM fleet policy.

## Risks

| Risk | Severity |
|------|----------|
| override.conf has KEEP_ALIVE=-1 (overridden by zz-) | LOW — zz- wins |
| num_ctx could be increased for richer context | LOW — enhancement, not safety |
