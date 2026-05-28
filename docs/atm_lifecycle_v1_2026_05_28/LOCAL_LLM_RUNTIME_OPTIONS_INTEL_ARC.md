# Local LLM Runtime Options — Intel Arc

**Date:** 2026-05-28
**Hardware:** Intel Arc Pro B50 (BMG G21, Battlemage) + Iris Xe (ADL GT2 iGPU)
**Vulkan driver:** 25.2.8, API 1.4.318

---

## Current Runtime

| Item | Value |
|------|-------|
| Ollama version | **0.20.6** |
| Latest stable | **v0.24.0** (2026-05-14) |
| Latest pre-release | v0.30.0-rc29 (2026-05-13) |
| Production model | gemma3:4b (Q4_K_M, 4.3B params) |
| Inference backend | Vulkan via Ollama |
| GPU offload | 41/41 layers on Arc B50 |
| VRAM usage | ~7.2 GB |
| Keep alive | 5m (systemd override active) |
| Max loaded models | 1 |
| Health check | PASS (7/7) |

## Version Gap Analysis

### Current: v0.20.6 → Latest stable: v0.24.0

4 minor versions behind. Key changes in v0.21–v0.24:
- Improved Vulkan backend stability
- Better memory management for multi-GPU systems
- Flash attention improvements
- KV cache optimizations
- New model format support

### Update recommended now?

**NO.** The current runtime is stable and passing all health checks. Classifier enrichment just landed and needs validation cycles before changing the inference layer. Update should be scheduled after:
1. Classifier apply phase completes successfully
2. Trade close analyzer batch runs clean
3. At least one full trading week on current stack

### v0.30.0-rc29 pre-release risk

v0.30 is a major pre-release with significant architecture changes. **Do not install.** Pre-release candidates on Intel Arc Vulkan have historically broken:
- GPU layer detection
- VRAM allocation
- Vulkan shader compilation
- Keep-alive behavior

The far-future expiration bug (year 2318) seen earlier this session was likely related to keep-alive handling in older Ollama builds. The systemd override now mitigates this.

## Disabled Models

| Model | Status | Reason |
|-------|--------|--------|
| qwen3:14b | BLOCKED | Hangs on GPU, 16GB VRAM overcommit, far-future keep_alive |
| gemma4:e2b | BLOCKED | Canary failed |
| gemma4:e4b | BLOCKED | Canary failed |

These remain in `DISABLED_LOCAL_LLM_MODELS` and are blocked by the safety router at the application level.

## Production Model: gemma3:4b

- Stable on Vulkan with Arc B50
- ~3-12s per classifier call (GPU offloaded)
- JSON output reliable with parser fixes
- Passes numeric and structured JSON health tests
- Sufficient quality for enriched classifier (20/20 evidence-based classifications)

## Alternative Runtime Options

### 1. llama.cpp Vulkan Direct Server

**What:** Run llama.cpp's `llama-server` directly with `--gpu-layers` and Vulkan backend, bypassing Ollama.

**Pros:**
- Direct control over Vulkan device selection (GGML_VK_VISIBLE_DEVICES)
- No Ollama abstraction layer — fewer bugs
- Faster iteration on model parameters
- Flash attention and KV cache control at CLI level
- Compatible with same GGUF model files

**Cons:**
- No model management (manual GGUF file handling)
- No automatic model pulling
- Must build from source for Intel Vulkan support
- API is OpenAI-compatible, not Ollama-compatible (code changes needed)

**Verdict:** Best canary candidate. Test with gemma3:4b GGUF first. Do not deploy to production until Ollama path is proven unreliable.

### 2. IPEX-LLM (Intel Extension for PyTorch)

**What:** Intel's optimized PyTorch extension for XPU (Arc/Xe) inference.

**Pros:**
- Native Intel GPU support via oneAPI/Level Zero
- Optimized kernels for Intel hardware
- Supports INT4/INT8 quantization
- Can serve via vLLM or transformers pipeline

**Cons:**
- Requires oneAPI toolkit installation (large dependency)
- Level Zero driver stack different from Vulkan path
- Not GGUF-compatible — needs HuggingFace format
- Higher complexity to deploy and maintain
- May conflict with existing Vulkan/Ollama setup

**Verdict:** High potential but high migration cost. Only consider if Vulkan path proves fundamentally broken on Battlemage.

### 3. OpenVINO GenAI

**What:** Intel's inference optimization toolkit with GenAI pipeline.

**Pros:**
- Hardware-optimized for Intel GPUs
- Good INT8/INT4 quantization
- Stable deployment track record
- OpenVINO model format is well-tested

**Cons:**
- Requires model conversion to OpenVINO IR format
- Different serving API
- Less community model support than GGUF ecosystem
- Another dependency stack to maintain

**Verdict:** Enterprise-grade option. Overkill for current workload. Revisit if scaling to multiple models or higher throughput.

### 4. Open WebUI / LM Studio

**What:** GUI-based LLM interfaces that can use Ollama as backend.

**Pros:**
- Easy manual testing and prompt iteration
- Visual model management
- Good for prompt engineering sessions

**Cons:**
- Not suitable for automated pipeline integration
- Additional resource consumption
- No API automation advantage over current setup

**Verdict:** Manual testing only. Not a production alternative.

## Recommended Next Steps

1. **Keep current production runtime stable.** Ollama 0.20.6 + gemma3:4b + Vulkan is working. Do not change during classifier validation phase.

2. **Schedule Ollama update to v0.24.0** after classifier apply phase is validated (target: next week). Back up current binary first:
   ```bash
   sudo cp /usr/local/bin/ollama /usr/local/bin/ollama.0.20.6.bak
   ```

3. **Create llama.cpp Vulkan canary** only after:
   - Classifier apply completes successfully
   - Trade close analyzer batch runs clean
   - At least 5 trading days on enriched classifier
   - Canary runs in parallel, not replacing Ollama

4. **Do not install IPEX-LLM or OpenVINO** unless Vulkan path fails. Current stack is sufficient.

5. **Do not enable gemma4 or qwen3** until their specific failure modes are diagnosed and documented.

## Rollback

Current runtime requires no rollback — no changes were made. If a future Ollama update breaks inference:
```bash
sudo systemctl stop ollama
sudo cp /usr/local/bin/ollama.0.20.6.bak /usr/local/bin/ollama
sudo systemctl start ollama
```
