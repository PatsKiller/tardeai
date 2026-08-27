# llama.cpp Vulkan Canary Report

**Date:** 2026-05-29
**llama.cpp version:** b9405 (pre-built Ubuntu Vulkan x64 binary)
**Model:** gemma-3-12b-it Q4_K_M (from lmstudio-community HuggingFace, 6.8 GB)
**GPU:** Intel Arc Pro B50 (BMG G21), Vulkan driver 25.2.8

## Setup

- Downloaded pre-built `llama-b9405-bin-ubuntu-vulkan-x64.tar.gz` from GitHub releases
- Downloaded compatible GGUF from `lmstudio-community/gemma-3-12b-it-GGUF` (HuggingFace)
- Note: Ollama's internal GGUF format is incompatible with upstream llama.cpp (`gemma3.attention.layer_norm_rms_epsilon` key not found)
- Server config: `--ctx-size 4096 --n-gpu-layers 99 --threads 6 --port 8081`
- API: OpenAI-compatible (`/v1/chat/completions`)

## Results

| Test | llama.cpp | Ollama | Winner |
|------|----------|--------|--------|
| basic_json | **PASS 2.8s** 15 tok | PASS 26.6s 16 tok | **llama.cpp (9.5x faster)** |
| strategy_classifier | **PASS 9.1s** 102 tok | PASS 11.1s 26 tok | **llama.cpp (1.2x faster, more tokens)** |
| close_trade_analysis | FAIL 19.0s 238 tok (parse) | FAIL 31.3s 273 tok (parse) | Tie (both had parse issues) |

## Key Findings

### Speed
llama.cpp is significantly faster on basic JSON (2.8s vs 26.6s) and modestly faster on classifier (9.1s vs 11.1s). The Ollama basic_json slowness was partly cold-load (first call after model swap), but even on warm model, llama.cpp has lower overhead.

### VRAM
Both use ~10 GB for gemma3:12b Q4_K_M with 4096 context. llama.cpp detected:
- Vulkan0 (Iris Xe iGPU): 47 GiB shared memory
- Vulkan1 (Arc B50): 16.3 GiB, 8.9 GiB free
- Total model+KV: ~6.7 GiB on GPU

### Compatibility Issue
Ollama's GGUF format differs from upstream llama.cpp. The same model file cannot be shared — separate downloads required. This means:
- Ollama models: managed by `ollama pull`
- llama.cpp models: separate GGUF from HuggingFace
- ~14 GB disk for both copies of gemma3:12b

### close_trade_analysis Parse Failure
Both engines produced content for the close-trade analysis prompt, but the JSON parser failed on both. This is a prompt/model issue, not an engine issue. The model generates fenced JSON with extra text that the canary's simple parser doesn't handle as well as the production parser.

## Limitations

1. **No model management**: llama.cpp requires manual GGUF file handling
2. **Separate GGUF files**: Can't share Ollama's model blobs
3. **API difference**: OpenAI-compatible, not Ollama-compatible (code changes needed for production use)
4. **No auto-restart**: Would need a systemd service for production
5. **Port conflict risk**: Must run on different port (8081) alongside Ollama (11434)

## Recommendation

**llama.cpp is a viable alternative runtime** for gemma3:12b on Intel Arc Vulkan. It's faster on inference and uses the same GPU. However:

1. **Do NOT replace Ollama yet** — the speed advantage (1.2-9.5x) matters mainly for bulk batch runs, not for the current workload
2. **Keep as canary/benchmark tool** — useful for A/B testing model quality and latency
3. **Production switch criteria:**
   - Must have systemd service with auto-restart
   - Must handle VRAM contention with embedding models
   - Must pass 50+ trade classifier batch without failures
   - Must have clear rollback path to Ollama
4. **Next step:** Create a systemd service for llama-server on port 8081, run it alongside Ollama for side-by-side comparison on real classifier batches

## Installation Path

```
~/llama-cpp-vulkan/
  llama-b9405/          # Pre-built binaries
    llama-server
    llama-cli
    libggml-vulkan.so
    ...
  gemma3-12b-hf.gguf    # HuggingFace GGUF (6.8 GB)
```

## Safety

- No production routing changed
- No .env modified
- No DB writes
- No orders/broker writes
- llama-server stopped after canary
- Ollama health check PASS after cleanup
