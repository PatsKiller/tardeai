# Local LLM Model Tier Decision — Gemma3:12b

**Date:** 2026-05-28
**Ollama:** 0.24.0

## Model Tiers

| Tier | Model | Role | GPU/Vulkan | Status |
|------|-------|------|-----------|--------|
| **Production (fast)** | gemma3:4b | Default classifier, analyzer, all high-volume jobs | PASS | Active |
| **Review (adjudicator)** | gemma3:12b | Quality pass, adjudication, second opinions | PASS | Approved for dry-run use |
| Disabled | qwen3:14b | N/A | N/A (VRAM overcommit) | Installed, blocked by router |
| Removed | gemma4:e2b | N/A | FAIL (HTTP 500) | Uninstalled |
| Removed | gemma4:e4b | N/A | FAIL (garbage output) | Uninstalled |

## gemma3:12b Approved Use Cases

- Classifier adjudication: second-pass on needs_review or conflict trades
- Close-trade analysis quality pass: deeper review of LLM-generated assessments
- Delayed review summaries: non-time-critical batch analysis
- Monthly learning summaries: if local-only inference is desired
- Model comparison dry-runs: A/B testing against gemma3:4b

## gemma3:12b Prohibited Use Cases

- High-volume default classification (use gemma3:4b)
- Always-on background jobs (VRAM headroom too tight at 9.75 GB)
- Concurrent jobs (MAX_LOADED_MODELS=1, MAX_CONCURRENT=1)
- Embeddings (use nomic-embed-text or qwen3-embedding:8b)
- Production router default (requires operator approval to promote)

## Operational Requirements

- Max concurrent local generation jobs: **1**
- Must unload gemma3:4b before loading gemma3:12b (or let Ollama auto-swap with MAX_LOADED=1)
- Requires `num_ctx=4096` or similar bounded value — default 131072 causes VRAM overcommit on model swap
- Any use must be dry-run first and audited
- Must run health check after use to confirm gemma3:4b is restored

## Canary Evidence

| Test | gemma3:4b | gemma3:12b |
|------|-----------|------------|
| basic_json | ~3s | 4.6s |
| strategy_classifier | ~10s | 12.5s |
| close_trade_analysis | ~12s | 21.8s |
| VRAM | 7.2 GB | 9.75 GB |
| 10-trade classifier | 10/10 (1 inconsistency) | 10/10 (0 inconsistencies) |
| APAM-469 consistency | speculative_growth (0.5, conflict) | dividend_growth_compounder (0.85, correct) |

## .env Policy

No changes. gemma3:12b is NOT in `LOCAL_LLM_MODEL` or `LOCAL_LLM_SAFE_MODEL`. It is called explicitly by model name when needed, bypassing the default router.

```
LOCAL_LLM_MODEL=gemma3:4b
LOCAL_LLM_SAFE_MODEL=gemma3:4b
DISABLED_LOCAL_LLM_MODELS=qwen3:14b,gemma4:e2b,gemma4:e4b
```

## Promotion Criteria

To promote gemma3:12b to production default, all of these must be met:

1. 50+ trade classifier apply with 0 errors
2. Output quality equal or better than gemma3:4b on same trades
3. No VRAM crashes or Ollama restarts during batch
4. `num_ctx` integration into classifier and analyzer scripts
5. Explicit operator approval
