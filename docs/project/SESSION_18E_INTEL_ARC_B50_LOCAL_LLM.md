# Session 18E: Intel Arc B50 Local LLM Model + GPU Runtime Centralization

**Date:** 2026-05-06
**GPU:** Intel Arc Pro B50 16GB
**Model:** qwen3:14b (centralized via LOCAL_LLM_MODEL)

## Summary

Centralized all local LLM model selection through `scripts/local_llm_config.py`.
Removed hardcoded `qwen3:1.7b` references from operational code.
Configured Intel Arc / Vulkan-safe Ollama environment settings.
Added system health visibility for provider, model, backend, and GPU/runtime status.

## Central Config Module

```python
# scripts/local_llm_config.py
from local_llm_config import get_local_llm_model, get_local_llm_base_url, apply_ollama_runtime_env

model = get_local_llm_model()       # resolves LOCAL_LLM_MODEL from .env
apply_ollama_runtime_env()           # sets Vulkan env vars
```

## .env Configuration

```env
LOCAL_LLM_PROVIDER=ollama
LOCAL_LLM_MODEL=qwen3:14b
LOCAL_LLM_BASE_URL=http://localhost:11434
LOCAL_LLM_BACKEND=vulkan
LOCAL_LLM_REQUIRE_GPU=true
```

## Ollama Systemd Override (Intel Arc / Vulkan)

Client-side env vars only affect subprocesses, not an already-running systemd service.
For persistent GPU acceleration, create a systemd override:

```bash
sudo systemctl edit ollama
```

Add:

```ini
[Service]
Environment="OLLAMA_VULKAN=1"
Environment="GGML_VK_VISIBLE_DEVICES=0"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=30m"
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
sudo systemctl status ollama --no-pager
```

Verify:

```bash
systemctl show ollama --property=Environment
ollama list | grep qwen3
ollama run qwen3:14b "Reply with exactly: qwen3-14b-ready"
```

## GPU Visibility Checks

```bash
lspci | grep -Ei "vga|display|intel|arc"
vulkaninfo --summary | head -80
clinfo -l
```

Monitor during inference:

```bash
sudo intel_gpu_top
```

## API Endpoints

- `GET /api/v2/local-llm-status` — full local LLM status with provider, model, backend, runtime env, loaded models
- `GET /api/v2/rewrite-note/status` — quick local LLM availability check

## Important Notes

- **Do NOT use** `HSA_OVERRIDE_GFX_VERSION` — that is AMD ROCm, not Intel Arc
- **Do NOT use** `nvidia-smi` — no NVIDIA GPU present
- **ZE_AFFINITY_MASK** only needed if using Level Zero / oneAPI / SYCL runtime
- The Vulkan path (`OLLAMA_VULKAN=1`) is the correct path for Intel Arc through Ollama
