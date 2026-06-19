# LLM Fleet v4.1 — Deployment Log

**Status:** Phase 0 COMPLETE — fleet stable as of 2026-06-19
**Operator:** johnclaw
**Commit at deploy:** aebd25db

## Active Fleet (live as of 2026-06-19)

| Role            | Model              | Notes                              |
|-----------------|--------------------|------------------------------------|
| Default/TradeAI | gemma3:4b          | Stable; canary-verified 2026-06-06 |
| Hermes sidecar  | gemma3:12b         | num_ctx=4096 required on /v1 path  |
| Overnight batch | gemma3:27b         | Long-context, overnight only       |
| Embeddings      | qwen3-embedding:8b | Active; replaces nomic-embed-text  |
| DISABLED        | qwen3:14b          | Uninstalled — NOT available        |

> Verified against `ollama list` 2026-06-19: gemma3:4b, gemma3:12b (+ ctx4k variant), gemma3:27b,
> gemma3-overnight, qwen3-embedding:8b present; qwen3:14b NOT installed. `.env`:
> `LOCAL_LLM_MODEL=gemma3:4b`, `DISABLED_LOCAL_LLM_MODELS=qwen3:14b,gemma4:e2b,gemma4:e4b`.

## Key Policy

- qwen3:14b is DISABLED and uninstalled. Agent configs naming it will FAIL.
- gemma3:12b requires `num_ctx=4096` on the Ollama /v1/chat path; native /api/generate is stable.
- All routing changes must go through `scripts/local_llm_config.py` — do NOT create a competing config layer.
- Cloud primary: `openai/gpt-5.4-mini`; fallback: `claude-sonnet-4-6`.

## Deferred Evaluation

| Item                          | Calendar Date | Pre-conditions                                      |
|-------------------------------|---------------|-----------------------------------------------------|
| gemma4:26b-a4b re-evaluation  | 2026-08-11    | v4.1 stable 30+ days; Ollama 2+ minor releases with MoE-on-Vulkan; side-by-side benchmark vs gemma3:27b on multi_strategy_classifier.py (7-day overnight); document results here |

## Phases

- **Phase 0:** COMPLETE (fleet routing stable, canary verified)
- **Phase 1:** NOT APPROVED — requires separate explicit operator approval
- **Phases 2–4:** GATED — do not treat as pre-approved

## Change History

| Date       | Change                                           | Commit   |
|------------|--------------------------------------------------|----------|
| 2026-06-19 | File created; captures Phase 0 completion state  | aebd25db |
| 2026-06-06 | gemma3:4b + gemma3:12b canary verified live      | —        |
| 2026-06-01 | gemma4 canary closed NOT_AVAILABLE               | —        |
| 2026-05-31 | v4.1 Final Execution Revision locked             | —        |
