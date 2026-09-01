# Memory Notes for Next Session — 2026-05-28

Status:      HISTORICAL
as_of:       2026-05-28T23:16:50-04:00
Measured at: efcc51365 / not measured

Durable context for the next Trade AI session. Read this before starting any LLM, classifier, or backtesting work.

## Local LLM Model Policy

- **Primary classifier/review model: gemma3:12b on GPU/Vulkan (Arc B50)** — better consistency than 4b, passed all workload canaries
- **Fast fallback model: gemma3:4b** — use only if gemma3:12b fails health/preflight, times out, or VRAM/load guard fails
- Do NOT use qwen3:14b — installed but disabled (CPU too slow, GPU VRAM overcommit)
- Do NOT use Gemma4 on Vulkan — gemma4:e2b and gemma4:e4b removed after GPU failures
- Do NOT use gemma3:27b on GPU
- Do NOT call Grok
- Max concurrent local generation jobs: 1
- gemma3:12b requires num_ctx=4096 to avoid VRAM overcommit on model swap
- Embedding models (nomic-embed-text, qwen3-embedding:8b) are separate and unaffected

## Ollama Configuration

- Version: **0.24.0**
- Systemd safety override active: OLLAMA_KEEP_ALIVE=5m, OLLAMA_MAX_LOADED_MODELS=1, OLLAMA_NUM_PARALLEL=1
- Drop-in: `/etc/systemd/system/ollama.service.d/99-tradeai-llm-safety.conf`
- Do NOT update Ollama without explicit operator approval

## Health Check Requirement

- `scripts/check_local_llm_health.py` must PASS (7/7) before any LLM-backed classifier or backtesting action
- The health check verifies: Ollama reachable, qwen not loaded, gemma3 numeric + JSON, disabled model routing, max one model, no unsafe jobs

## Classifier State

- **55-trade apply completed** (batch 1) — 34 strategy_backtest_trades rows updated
- **Source/writer mismatch FIXED** (commit ae8efe0): `--apply` now requires `--source strategy_backtest_trades` which reads/writes the same table. `--source trades_view` is read-only (trade_transactions has no strategy_id column)
- **Batch 2 should NOT be rerun via old path** — use `--source strategy_backtest_trades` instead
- **2,567/2,568 backtest trades classified** — only SHFS (id=860) remains unclassified (no enrichment data)
- V classified as dividend_growth_compounder. FJSCX x2 classified as speculative_growth (0.5, conflict flagged)
- **Hold-period gate active**: 0-day hard gate, 1-5d caution gate, enrichment conflict detection, ADBE source-data rule
- **Classifier default model**: gemma3:12b (set in script, not .env)
- **Rollback SQL**: `docs/atm_lifecycle_v1_2026_05_28/classifier_apply/classifier_apply_55_rollback.sql`

## Backtesting Source Distinction

- Champion simulations are hypothetical — do NOT treat as real trades
- Replay trades are actual paper trade replays
- Real paper trades are actual Alpaca/Schwab executions
- Default backtesting view must not make champion simulations look like real trades
- Filters must be data-driven and source-aware

## Safety Policy

- ALPACA_MODE=paper — do NOT change
- LLM_DISABLE_LIVE_EXECUTION=true — do NOT change
- No live execution
- No bulk apply without pre-state export and rollback SQL
- gemma3:12b primary for classifier/review; gemma3:4b as fallback only
