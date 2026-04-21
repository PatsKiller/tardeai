# Intel Arc Pro B50 + Qwen3 Local LLM Setup Guide

**Target hardware:** MS-01 mini PC (64GB RAM, Ubuntu) + Intel Arc Pro B50 16GB GDDR6  
**Target software:** Ollama or llama.cpp via IPEX-LLM for GPU-accelerated local inference  
**Primary use cases:**
1. Replace qwen3:1.7b in portfolio_ai_analyst.py with qwen3:14b for weekly AI Deep Analysis
2. Run qwen3-coder:14b for Claude Code-alternative local development via Qwen Code CLI

---

## Critical caveat to read first

Intel Arc Pro B50 is a **workstation graphics card**, not an LLM-optimized GPU. Its 128-bit memory bus gives ~224 GB/s bandwidth — substantially lower than used RTX 3090 (936 GB/s) at similar price. For LLM inference, memory bandwidth matters more than compute.

**Expected performance on B50 (rough estimates, verify with actual benchmarks):**
- qwen3:8b Q4: 15-25 tokens/sec
- qwen3:14b Q4: 8-15 tokens/sec
- qwen3-coder:14b Q4: 8-15 tokens/sec

Compare to:
- qwen3:1.7b on CPU: 5-10 tokens/sec (what you have now)
- qwen3:14b on RTX 3090: 40-60 tokens/sec

**B50 will be faster than CPU-only, slower than NVIDIA equivalents.** For weekly pipeline use (batch generation of AI sections, not interactive), this is acceptable. For interactive coding (Qwen Code), you may feel the latency.

Also: **Intel GPU LLM stack is less mature than NVIDIA CUDA**. Expect more setup friction, occasional driver-version-specific quirks, and a smaller pool of Stack Overflow answers when something breaks. Budget extra time.

---

## Part 1: Pre-install hardware verification

### Physical checks

```bash
# Verify MS-01 has a free PCIe slot
lspci | grep -i "pci bridge"

# Check current PSU capacity vs. card draw
# B50 draws ~75W peak (low-power card, no external PCIe power connectors)
# Most MS-01 models can handle this from the slot alone, but verify
```

MS-01 typically has one PCIe x16 slot (often wired as x8 or x4). B50 is PCIe 5.0 x8, which works fine in x16, x8, or even x4 slots with some performance loss.

**Power draw is the good news:** B50 is a 75W card with no external power connectors required. Your MS-01's existing power brick should handle it. This is easier than the NVIDIA 16GB options (165W+) which likely would NOT fit the MS-01 thermal/power envelope.

### Install GPU physically

1. Power off, unplug everything
2. Open MS-01 chassis
3. Install B50 in PCIe slot, secure bracket
4. Close case, reconnect, power on
5. System should boot with output from either Intel integrated graphics or B50 depending on BIOS settings

### Driver verification

First boot with Arc Pro B50:

```bash
# Check if kernel detected the GPU
lspci | grep -i "vga\|display\|3d"
# Expected: Intel Arc Pro B50 or similar

# Check kernel version — IPEX-LLM requires kernel 6.5+
uname -r
```

If kernel is older than 6.5, you may need to upgrade. Ubuntu 24.04 ships with kernel 6.8+ which should be fine.

---

## Part 2: Install Intel GPU stack

Intel's LLM path is via **IPEX-LLM (Intel Extension for PyTorch LLM)**. This provides the backend that makes Ollama, llama.cpp, and other tools use the Intel GPU.

### 2.1 Install Intel GPU drivers

Ubuntu 24.04+:

```bash
# Add Intel GPU repo
sudo apt update
wget -qO - https://repositories.intel.com/graphics/intel-graphics.key | \
    sudo gpg --dearmor --output /usr/share/keyrings/intel-graphics.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/intel-graphics.gpg] https://repositories.intel.com/graphics/ubuntu noble main" | \
    sudo tee /etc/apt/sources.list.d/intel-gpu-noble.list

sudo apt update
sudo apt install -y \
    intel-opencl-icd \
    intel-level-zero-gpu \
    level-zero \
    intel-media-va-driver-non-free \
    libmfx1

# Add your user to video and render groups
sudo usermod -aG video,render $USER

# Reboot
sudo reboot
```

After reboot, verify:

```bash
# Should list the Arc Pro B50
clinfo | grep "Device Name"

# Should show /dev/dri/renderD128 or similar
ls -l /dev/dri/
```

### 2.2 Install IPEX-LLM

IPEX-LLM is a Python package that adds Intel GPU support to various LLM runners.

```bash
# Create a dedicated Python environment (don't pollute your portfolio .venv)
python3 -m venv ~/llm-venv
source ~/llm-venv/bin/activate

# Install IPEX-LLM with GPU support
pip install --pre --upgrade ipex-llm[xpu] \
    --extra-index-url https://pytorch-extension.intel.com/release-whl/stable/xpu/us/
```

Verify IPEX-LLM sees the GPU:

```bash
python3 -c "
import torch
import intel_extension_for_pytorch as ipex
print('XPU available:', torch.xpu.is_available())
print('Device count:', torch.xpu.device_count())
print('Device name:', torch.xpu.get_device_name(0))
"
```

Expected output:
```
XPU available: True
Device count: 1
Device name: Intel(R) Arc(TM) Pro B50 Graphics
```

If XPU is not available, check:
- `clinfo` output — is the device listed?
- User is in `video` and `render` groups (`groups` command)
- Kernel modules loaded (`lsmod | grep i915`)

---

## Part 3: Choose your runner — Ollama vs llama.cpp

You have two practical options for serving models on the B50.

### Option A: Ollama with IPEX-LLM (easier, less performance)

Ollama itself doesn't yet natively support Intel XPU (as of my knowledge cutoff). To make it work, you use IPEX-LLM's Ollama wrapper.

```bash
# Install IPEX-LLM's Ollama distribution
pip install --pre --upgrade ipex-llm[cpp] \
    --extra-index-url https://pytorch-extension.intel.com/release-whl/stable/xpu/us/

# This provides `init-ollama` command that sets up Ollama with Intel GPU backend
init-ollama
```

Then start Ollama pointing at Intel GPU:

```bash
export OLLAMA_NUM_GPU=999  # offload all layers to GPU
export no_proxy=localhost,127.0.0.1
export ZES_ENABLE_SYSMAN=1
source /opt/intel/oneapi/setvars.sh  # if oneapi is installed; otherwise skip

./ollama serve
```

In another terminal, pull and test models:
```bash
./ollama pull qwen3:8b
./ollama run qwen3:8b "Hello, what is 2+2?"
```

**Advantages:** Familiar Ollama interface, same API your portfolio code already uses.  
**Disadvantages:** Intel GPU support through IPEX-LLM is a layer of translation; slight performance overhead vs. llama.cpp.

### Option B: llama.cpp with SYCL backend (best performance)

llama.cpp has native Intel GPU support via SYCL. Slightly more setup, better performance.

```bash
# Install build dependencies
sudo apt install -y build-essential cmake intel-oneapi-compiler-dpcpp-cpp

# Clone and build llama.cpp with SYCL
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
source /opt/intel/oneapi/setvars.sh
cmake -B build -DGGML_SYCL=ON -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx
cmake --build build --config Release -j
```

Download a model:
```bash
# Qwen3 models are on HuggingFace
# Use GGUF format for llama.cpp
wget https://huggingface.co/Qwen/Qwen3-14B-Instruct-GGUF/resolve/main/qwen3-14b-instruct-q4_k_m.gguf \
    -O models/qwen3-14b-q4km.gguf
```

Run:
```bash
./build/bin/llama-server \
    -m models/qwen3-14b-q4km.gguf \
    --port 11434 \
    -ngl 99 \
    --host 0.0.0.0
```

This serves an OpenAI-compatible API on port 11434 (same as Ollama). Your portfolio code may work with minor endpoint adjustments.

**Advantages:** Better performance, fewer moving parts.  
**Disadvantages:** You replace Ollama — need to adapt any code that uses Ollama-specific endpoints (`/api/generate`).

### Recommendation

Start with **Option A (Ollama + IPEX-LLM)** because your portfolio code already targets Ollama's `/api/generate` endpoint on port 11434. Minimum code changes. If performance is insufficient, switch to Option B later.

---

## Part 4: Model selection and tuning

### Models to pull

Start with one or two, add more after verifying quality/speed:

```bash
# General-purpose for portfolio analysis
./ollama pull qwen3:8b      # ~5GB, faster
./ollama pull qwen3:14b     # ~9GB, better quality

# Code model for Qwen Code CLI
./ollama pull qwen3-coder:14b  # ~9GB

# Keep current as fallback
# qwen3:1.7b is already installed
```

All three models together = ~20-25GB disk. Each loads one-at-a-time into VRAM; Ollama swaps as needed.

### Tune context window

Default Ollama `num_ctx` is often 2048 — too small for portfolio analysis that includes account breakdowns, holdings list, ETF look-through, etc.

Create a custom model variant with extended context:

```bash
./ollama show qwen3:14b --modelfile > /tmp/qwen3-14b.modelfile

# Edit: add line
# PARAMETER num_ctx 8192

./ollama create qwen3:14b-portfolio -f /tmp/qwen3-14b.modelfile
```

Now reference `qwen3:14b-portfolio` in your portfolio code.

**Note on VRAM:** Larger `num_ctx` uses more VRAM. 8192 context on qwen3:14b at Q4 = ~11-12GB VRAM. On 16GB you have headroom. If you want 16K context, may need to drop to qwen3:8b.

### Keep model warm

By default Ollama unloads models after 5 minutes idle. For portfolio pipeline runs that cluster (weekly runs generate 7 sections back-to-back), this is fine. For interactive use:

```bash
export OLLAMA_KEEP_ALIVE=24h
```

Put this in your systemd unit file or shell profile.

---

## Part 5: Update portfolio_ai_analyst.py

After Phase 1 of the rewrite scope (removing hardcoded numbers), update the Ollama model reference:

**Current (line 25 and 47):**
```python
OLLAMA_MODEL = "qwen3:1.7b"
# and inside _ollama():
json={"model":"qwen3:1.7b", ...}
```

**New:**
```python
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b-portfolio")
# and inside _ollama():
json={"model":OLLAMA_MODEL, ...}
```

Then set in your environment:
```bash
export OLLAMA_MODEL=qwen3:14b-portfolio
```

Or in your systemd service file for the portfolio runner.

**Clear stale cache and regenerate:**
```bash
rm -f data/portfolios/state/ai_*.json
python3 scripts/portfolio_ai_analyst.py --project-root . --run-type weekly
```

### Quality verification

Open CC AI tab. Read a few Deep Analysis sections. You should see:
- More specific, grounded analysis (qwen3:14b has 10x the parameters of 1.7b)
- Fewer hallucinated numbers (assuming Phase 1 of rewrite is done)
- Longer response time per section (8-15 tok/sec × 500 tokens = 30-60 sec per section)

Weekly pipeline with 7 sections × 45 sec = ~5 minute runtime. Acceptable for background job.

---

## Part 6: Qwen Code CLI setup (bonus — local coding agent)

Qwen Code is a CLI tool from the Qwen team offering Claude Code-style agentic workflows using local models.

**Verify before relying:** This tool evolves fast. Check https://github.com/QwenLM for current install instructions. Steps below are representative as of my knowledge cutoff.

### Install

```bash
# Requires Node.js 18+
node --version  # check
# If missing:
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install Qwen Code
npm install -g @qwen-code/qwen-code
```

### Configure for local Ollama

Create `~/.qwen-code/config.json`:

```json
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": "qwen3-coder:14b",
  "temperature": 0.2,
  "max_tokens": 4096
}
```

### Usage

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
qwen-code
```

You'll get a Claude Code-style prompt. Try simple tasks first:
- "Show me what scripts/portfolio_signals.py does in one paragraph"
- "Add a docstring to the top of portfolio_monthly_report.py"

**Realistic expectations:** qwen3-coder:14b on B50 will be slower than Claude Code on Anthropic's API. Good for tinkering, learning, privacy-sensitive work. Not a replacement for Claude Code on production refactors.

---

## Part 7: Troubleshooting

### GPU not detected

```bash
# Check driver loaded
lsmod | grep i915

# Check device present
lspci -k | grep -A 3 "VGA\|3D"

# Check OpenCL can see it
clinfo

# Check permissions
ls -l /dev/dri/
groups | grep -E "video|render"
```

If any fail, revisit Part 2.

### IPEX-LLM can't find XPU

```bash
# Inside the llm-venv:
python3 -c "import torch; print(torch.xpu.is_available())"
```

If False:
- Reboot after installing drivers (required)
- Check `dmesg | grep -i i915` for driver errors
- Reinstall ipex-llm via the Intel index URL (not regular PyPI)

### Model runs but uses CPU not GPU

In a separate terminal while model runs:
```bash
# Intel GPU utilization monitor
intel_gpu_top
```

If utilization stays low and CPU is maxed, GPU offload isn't working. Check:
- `OLLAMA_NUM_GPU=999` environment variable set
- IPEX-LLM version matches your PyTorch version
- Try smaller model first (qwen3:8b) to isolate memory issues

### Out of memory

qwen3:14b Q4 + 8K context = ~12GB VRAM. Leaves 4GB for other GPU tasks. If OOM:

- Reduce `num_ctx` (8192 → 4096)
- Use Q3 quantization instead of Q4 (`qwen3:14b-q3_k_m` variant)
- Close other GPU consumers (`intel_gpu_top` shows who)
- Drop to qwen3:8b

### Slow inference

- Verify GPU is actually being used (`intel_gpu_top`)
- Check thermal throttling (`sensors` command, GPU temps)
- MS-01 airflow may be marginal — B50 is passive or low-fan, relies on case airflow
- Lower `num_ctx` if context is consistently under 4K in practice

### Regressions in portfolio output after GPU swap

If AI Deep Analysis quality gets WORSE after moving to qwen3:14b on GPU:
- Check OLLAMA_MODEL environment variable is set
- Run `ollama ps` to see which model is actually loaded
- Clear AI cache: `rm data/portfolios/state/ai_*.json`
- Verify the model was pulled with the right tag

---

## Part 8: Honest cost/benefit analysis

### Hardware cost
- Intel Arc Pro B50: ~$400-500 (you bought)
- Electricity at 75W × 4 hrs/day × 365 days × $0.20/kWh = ~$22/year

### What you get
- Faster weekly AI Deep Analysis (30-60 sec vs. 2-5 min per section on CPU)
- Better analysis quality (qwen3:14b > qwen3:1.7b meaningfully)
- Private local coding agent (Qwen Code)
- GPU for other tasks (video encoding, maybe small image gen)

### What you don't get
- Sonnet-level analysis quality (qwen3:14b is ~GPT-3.5 tier, not Sonnet tier)
- Reliability (local models hallucinate more than Sonnet)
- Reproducibility (model versions change, quantization affects output)

### Where the B50 pays off
- Weekly pipeline automation (runs in background, slower is fine)
- Privacy-sensitive work (financial data never leaves LAN)
- Learning and tinkering with LLMs at zero marginal cost
- Specific use cases where API costs add up (high-volume analysis)

### Where Sonnet API wins
- Monthly flagship analysis (Commander's Summary, Roth conversion advice)
- Any time correctness of specific numbers matters (tax, concentration, signals)
- Situations where you'd share output with others or use it for decisions

### Architectural recommendation

**Use local LLM (B50) for:**
- Weekly Deep Analysis sections (draft quality OK)
- Qwen Code tinkering sessions
- Exploratory prompting

**Use Sonnet API for:**
- Monthly Commander's Summary
- Monthly Executive Brief (the new section from Phase 3)
- V Concentration Strategy (high-stakes position decision)
- Roth Conversion Advisory (tax/timing)
- Defense Portfolio thesis analysis (critical to AI WWIII strategy)

**Use Opus API for:**
- Monthly flagship synthesis (once per month)
- Ad-hoc complex analysis when stakes are high

Budget: Monthly Sonnet + Opus usage at your volume = $5-15/month. Worth it for reliability on high-stakes sections.

---

## Summary: Setup checklist

### Day of GPU install
- [ ] Physical install B50 in MS-01
- [ ] Boot, verify kernel detects card (`lspci`)
- [ ] Install Intel GPU drivers (Part 2.1)
- [ ] Reboot, verify OpenCL sees device (`clinfo`)
- [ ] Install IPEX-LLM (Part 2.2)
- [ ] Verify XPU available from Python

### First model run
- [ ] Install ipex-llm's Ollama wrapper (Part 3 Option A)
- [ ] Start Ollama with Intel GPU backend
- [ ] Pull qwen3:8b, run hello-world test
- [ ] Monitor `intel_gpu_top` — verify GPU utilization

### Portfolio integration
- [ ] Complete Phase 1 of portfolio_ai_analyst.py rewrite (hardcoded numbers) FIRST
- [ ] Create qwen3:14b-portfolio variant with extended context
- [ ] Update OLLAMA_MODEL env var
- [ ] Clear AI cache
- [ ] Run weekly pipeline, verify improved output quality
- [ ] Compare runtime and quality vs. CPU baseline

### Optional: Qwen Code
- [ ] Install Node.js 18+
- [ ] Install @qwen-code/qwen-code
- [ ] Configure for local Ollama
- [ ] Try basic file inspection task

---

## Tomorrow or weekend: recommended first session

When the GPU physically arrives and you're ready to set it up:

1. **Hardware install** (30 min) — Parts 1 checks + physical install
2. **Drivers** (30-60 min) — Part 2 install, reboot, verify
3. **Ollama + IPEX-LLM** (30-60 min) — Part 3 Option A, pull qwen3:8b, hello world
4. **Quick quality sniff test** (15 min) — run a simple portfolio-like prompt, compare output to qwen3:1.7b

**Stop there.** Don't integrate with the portfolio pipeline until you've confirmed GPU works and quality meaningfully improves. Pipeline integration requires Phase 1 of the rewrite scope to be done anyway.

Total: 2-3 hours for a clean first session. Then integration work happens after Phase 1 of the rewrite is done.
