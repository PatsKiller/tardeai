# Memory Notes for Next Session — 2026-05-29

Durable context for the next Trade AI session.

## Classifier State — COMPLETE

- **Source/writer mismatch is FIXED** (commit ae8efe0). `--apply` requires explicit `--source strategy_backtest_trades`.
- Do NOT use the legacy trades_view apply path — it is blocked.
- **3,592/3,593 backtest trades classified** (99.97%).
- **SHFS (id=860) is the only remaining unclassified** backtest row — needs enrichment data or manual classification.
- trade_transactions 153 rows show unclassified in the `trades` view — this is expected and permanent (no strategy_id column).
- No more bulk classifier batches needed.
- Rollback SQL: `docs/atm_lifecycle_v1_2026_05_28/classifier_apply/classifier_apply_55_rollback.sql`

## Backtesting Source Labels

- Champion simulations (BT_* run_id, 3,516 rows) = hypothetical — do NOT treat as real trades
- Replay trades (ER_* run_id, 77 rows) = actual trade replays
- Real paper trades = paper_trades table (38 with strategy_id, 16 closed)
- Filters must remain data-driven and source-aware

## Local LLM Model Policy

- **Primary classifier/review model: gemma3:12b on GPU/Vulkan** — better consistency than 4b
- **Fast fallback: gemma3:4b** — use only if 12b fails health/preflight/timeout/VRAM
- **Offline quality reviewer: gemma4:31b Q3_K_M on llama.cpp** — best output quality, 15-25x slower, hybrid GPU/CPU only
- Do NOT use qwen3:14b, gemma4 e2b/e4b, or gemma3:27b on GPU
- Do NOT call Grok
- Max concurrent local generation jobs: 1
- gemma3:12b requires `num_ctx=4096` to avoid VRAM overcommit on model swap
- Classifier default model is gemma3:12b (set in script, not .env)
- .env `LOCAL_LLM_MODEL=gemma3:4b` is the router fallback only

## llama.cpp Runtime

- Installed at `~/llama-cpp-vulkan/llama-b9405/` (pre-built Ubuntu Vulkan x64, b9405)
- GGUF models at `~/llama-cpp-vulkan/` (gemma3-12b-hf.gguf 6.8GB, gemma4-31b-hf.gguf 14GB)
- Ollama GGUF format is INCOMPATIBLE with upstream llama.cpp — separate downloads required
- llama-server runs on port 8081 (OpenAI-compatible API)
- NOT production — no systemd service, no auto-restart, no VRAM contention guard
- Keep Ollama as production runtime until llama.cpp passes 50+ trade batch validation

## Ollama Configuration

- Version: **0.24.0**
- Systemd override: KEEP_ALIVE=5m, MAX_LOADED=1, NUM_PARALLEL=1
- Health check: `scripts/check_local_llm_health.py` must PASS 7/7 before any LLM action

## Hardcoded Model References

- **FIXED** (commits 40c1ae1, b6e7571): 13 runtime scripts cleaned
- Remaining qwen3:14b references are only in comments/docstrings and historical validation scripts

## Safety

- ALPACA_MODE=paper — do NOT change
- LLM_DISABLE_LIVE_EXECUTION=true — do NOT change
- No live execution
- No bulk apply without pre-state export and rollback SQL
