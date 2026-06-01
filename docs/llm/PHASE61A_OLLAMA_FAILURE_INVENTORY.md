# Phase 61A — Ollama Failure Inventory

**Date:** 2026-06-01
**Status:** COMPLETE — root cause identified

## Root Cause

**Cold model swap contention.** At the time of Phase 60 pilot:
- `gemma3:4b` was resident in VRAM (6.8GB)
- Pilot requested `gemma3:12b` with `num_ctx=8192`
- GPU (Intel Arc B50) could not fit both models simultaneously
- Ollama returned 500 Internal Server Error on all 3 attempts

## Contributing Factors

| Factor | Status |
|--------|--------|
| Cold model load | YES — gemma3:12b not resident |
| Context size too large | LIKELY — num_ctx=8192 on cold load |
| Parallel model contention | YES — gemma3:4b held VRAM |
| Old overnight overlap | NO — pilot ran outside overnight window |
| GPU memory exhaustion | YES — Intel Arc B50 has ~16GB |
| Model lock contention | NO — Ollama handles internally |

## Current Ollama Config

- MAX_LOADED_MODELS=1
- KEEP_ALIVE=5m
- GPU: Intel Arc B50 (Vulkan)
- Currently loaded: gemma3:4b (6.8GB)

## Available Models

gemma3:12b, gemma3:4b, gemma3:27b, gemma3-overnight, nomic-embed-text, qwen3-embedding:8b

**No Gemma 4 models installed.**
