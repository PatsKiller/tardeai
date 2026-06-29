# Local LLM Runtime Policy — Intel Arc Pro B50

_Ratifies exactly which local models run, on which device, with which backend, and the market-hours
budget. Source of truth: `config/local_llm_runtime_policy.yaml`. Enforced by `llm_budget_guard` +
`local_llm_runtime_probe`. No paid fallback; no local 31B fallback in market hours. No broker writes._

## Hardware

| Device | Role | LLM generation |
|--------|------|----------------|
| **Intel Arc Pro B50** (Battlemage, discrete, ~16GB VRAM) | production GPU | ✅ pin here |
| Intel Iris Xe (integrated, shares 61GB RAM) | display / fallback | ❌ never for generation |

Pin to the discrete B50: **`GGML_VK_VISIBLE_DEVICES=1`** (device 0 = integrated Iris Xe). The probe FAILs
if `=0` (integrated selected) and WARNs if unset on the Vulkan path.

## Models (ratified)

| Lane | Model | Size | Role | Market hours |
|------|-------|------|------|:------------:|
| **local_quality** | **gemma3:12b** | 8.1GB | **production ceiling** — scalp advisory, proposal explanation | ✅ (≤8 calls/5m, 1 concurrent) |
| **local_fast** | **gemma3:4b** | 3.3GB | classification, Social Scout labels, short summaries | ✅ (≤20 calls/5m, 2 concurrent) |
| **local_embed** | **nomic-embed-text** | 274MB | **protected** embeddings (90s timeout, pinned) | ✅ |
| local_fallback_benchmark | qwen3:8b | 5.2GB | **benchmark/fallback only** — not promoted until measured | benchmark only |
| **blocked** | **gemma3:27b**, **gemma4-31b** | 17GB+ | exceed 16GB VRAM → CPU-spill (caused the outage) | ❌ **hard-blocked 06:00–12:00 ET** — cloud/overnight only |

## Backend

* **Production: Vulkan** (`llama-cpp-vulkan` / ollama). Pinned to the B50.
* **Benchmark candidates: Vulkan vs SYCL/oneAPI vs IPEX-LLM.** oneAPI 2025.3 + Level-Zero are installed.
  SYCL/oneAPI is **not promoted over Vulkan without measured local wins** and no dashboard/embed
  regression (`local_llm_benchmark.py`, off-hours only).

## Market-hours enforcement (`llm_budget_guard`)

* gemma3:27b / gemma4-31b → **hard_block** during 06:00–12:00 ET.
* Free-OAuth jobs → **no paid fallback** (hard_fail).
* T3 with cloud unavailable/over-budget → **defer** (never local-31B, never paid).
* Local lane limits: fast ≤20/5m, quality ≤8/5m; embed protected (90s).

## Probe & benchmark

* `local_llm_runtime_probe.py --json` — visible GPUs, device pin, backend, resident model, violations
  (unpinned / integrated-selected / blocked-model-resident-in-market / embed timeouts).
* `local_llm_benchmark.py` — off-hours only (refuses during market hours); measures ttft / latency /
  tokens-sec; never benchmarks 27B/31B in market hours; promotion is evidence-gated.

## Remaining runtime gaps

* **`GGML_VK_VISIBLE_DEVICES=1` is not yet set** on the llama-server launch — set it so generation pins to
  the discrete B50 (operator/launch-script change; the probe will then confirm `device_selected=discrete_arc_b50`).
* Backend is currently generic Vulkan — benchmark SYCL/oneAPI off-hours before any promotion.
* gemma4-31b should be removed from the local escalation path entirely (it's already market-hour-guarded).

No live trades, no broker writes, operator/2FA untouched. LLMs advisory only.
