# Memory Notes for Next Session — 2026-05-28

Durable context for the next Trade AI session. Read this before starting any LLM, classifier, or backtesting work.

## Local LLM Model Policy

- **Production generation model: gemma3:4b on GPU/Vulkan (Arc B50)**
- Do NOT use qwen3:14b for production generation — it remains installed but disabled (CPU too slow for workloads, GPU VRAM overcommit)
- Do NOT use Gemma4 on Vulkan — gemma4:e2b and gemma4:e4b were removed after GPU failures (CPU works, GPU produces garbage/500 errors on Ollama 0.24.0)
- Do NOT test or use Qwen5 — no official/validated Qwen5 local model is available
- Embedding models (nomic-embed-text, qwen3-embedding:8b) are separate and unaffected
- gemma3-overnight and gemma3:27b are installed but not production generation defaults

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
- **Batch 2 should NOT be rerun** — it produces 0 updates because the same trades resurface
- **Design gap**: classifier reads unclassified trades from the `trades` view (trade_transactions) but writes to `strategy_backtest_trades`. trade_transactions is never updated, so the same 55 trades always appear "unclassified"
- **Fix needed**: patch classifier to either update trade_transactions or skip already-classified symbols
- **4 remaining backtest trades**: V classified (dividend_growth_compounder). SHFS and FJSCX x2 are needs_review (insufficient enrichment data)
- **Hold-period gate active**: 0-day hard gate, 1-5d caution gate, enrichment conflict detection, ADBE source-data rule
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
- gemma3:4b only for production local generation
