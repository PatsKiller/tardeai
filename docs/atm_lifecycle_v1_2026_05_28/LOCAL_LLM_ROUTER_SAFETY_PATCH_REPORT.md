# Local LLM Router Safety Patch Report

**Date:** 2026-05-28
**Session:** Local LLM Safety Hardening

---

## Systemd Override

**Applied:** PENDING (requires sudo)

Commands to apply:
```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/99-tradeai-llm-safety.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_KEEP_ALIVE=5m"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Settings:
- `OLLAMA_KEEP_ALIVE=5m` (prevents far-future model persistence)
- `OLLAMA_NUM_PARALLEL=1` (single request at a time)
- `OLLAMA_MAX_LOADED_MODELS=1` (prevents VRAM overcommit)

## .env Safety Flags Applied

| Key | Value |
|-----|-------|
| LOCAL_LLM_MODEL | gemma3:4b |
| LOCAL_LLM_SAFE_MODEL | gemma3:4b |
| DISABLED_LOCAL_LLM_MODELS | qwen3:14b |
| FORCE_LOCAL_LLM_CPU | false |
| LOCAL_LLM_NUM_GPU | 41 (full GPU offload for gemma3:4b) |
| LOCAL_LLM_MAX_CONCURRENT | 1 |
| OLLAMA_KEEP_ALIVE | 5m |
| ALPACA_MODE | paper (unchanged) |
| LLM_DISABLE_LIVE_EXECUTION | true (unchanged) |

## Files Changed

| File | Change |
|------|--------|
| `scripts/local_llm.py` | Safety router: disabled model blocking, model resolution, pre-call cleanup, safety JSONL logging |
| `scripts/local_llm_config.py` | Default model changed qwen3:14b -> gemma3:4b |
| `scripts/check_local_llm_health.py` | NEW: 7-check health gate script |
| `scripts/trade_strategy_classifier.py` | Added LLM preflight gate before --apply, GPU-aware num_gpu |
| `scripts/trade_close_llm_analyzer.py` | Added LLM preflight gate before --apply, default model -> gemma3:4b, GPU-aware num_gpu |
| `.env` | Safety flags (not git-tracked) |

## Qwen3:14b Blocked Behavior

- `DISABLED_LOCAL_LLM_MODELS=qwen3:14b` blocks all requests
- `_resolve_model()` substitutes gemma3:4b and logs the block
- `_pre_call_cleanup()` unloads qwen3:14b if found loaded
- If qwen3:14b remains loaded after cleanup, system fails closed (returns None)

## Gemma3:4b Safe Model Behavior

- All generation requests resolve to gemma3:4b
- GPU offload: 41/41 layers on Intel Arc B50 Vulkan
- Numeric test: returned "4" correctly
- JSON test: returned valid `{"answer":4,"status":"ok"}` correctly
- Classifier dry-run: 3/3 trades classified successfully

## GPU Mode

- gemma3:4b runs with full GPU offload (num_gpu=41)
- ~3s per classification call vs ~60-90s on CPU
- Qwen3:14b remains blocked regardless of GPU/CPU setting

## Max Concurrent Local Jobs

- File lock at `/tmp/tradeai_local_llm_single_job.lock`
- `LOCAL_LLM_MAX_CONCURRENT=1`
- Only one Ollama request can run at a time across all processes

## Health Check Result

```
PASS — all 7 checks passed
- ollama_reachable: PASS
- qwen3_not_loaded: PASS
- gemma3_numeric: PASS (returned "4")
- gemma3_json: PASS (returned {"answer":4,"status":"ok"})
- disabled_model_routing: PASS (qwen3:14b -> gemma3:4b)
- max_one_model: PASS
- no_unsafe_jobs: PASS
```

## Classifier Dry-Run Result

```
3/3 trades classified (dry-run, no DB writes)
- AXTI: dividend_growth_compounder (0.9)
- APAM: dividend_growth_compounder (0.7)
- ADBE: dividend_growth_compounder (0.9)
```

## Trade Close Analyzer Dry-Run Result

```
1 backtest trade processed (dry-run, no DB writes)
- BLBD #119: meaningful_structured_review
- 579 tokens, 22.1s
- db_row_written: false
```

## Safety Confirmation

| Check | Status |
|-------|--------|
| Apply mode run | **NO** |
| LLM calls made | Health tests + dry-runs only |
| Grok called | NO |
| Cron changed | NO |
| Orders placed | NO |
| Broker writes | NO |
| paper_trades changes | NO |
| Proposal mutations | NO |
| Journal mutations | NO |
| Backtest mutations | NO |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |

## Loaded Models After Validation

- gemma3:4b (7.2GB VRAM, generation)
- nomic-embed-text:latest (578MB VRAM, embedding only)
- qwen3:14b: NOT loaded

## Rollback Command

```bash
# Restore .env
cp .env.bak_llm_safety_20260528_* .env

# Restore local_llm_config.py default
sed -i 's/DEFAULT_LOCAL_LLM_MODEL = "gemma3:4b"/DEFAULT_LOCAL_LLM_MODEL = "qwen3:14b"/' scripts/local_llm_config.py

# Remove systemd override
sudo rm /etc/systemd/system/ollama.service.d/99-tradeai-llm-safety.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama

# Git revert
git revert HEAD
```
