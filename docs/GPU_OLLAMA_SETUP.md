# Intel Arc B50 GPU Setup for Ollama

> **⚠️ Model policy (validated 2026-06-02):** gemma3:12b = primary chat, gemma3:4b = fallback, gemma3:27b = overnight; **qwen3-embedding:8b = embeddings (active)**; **qwen3:14b (chat) is DISABLED + uninstalled.** Any reference below to qwen3:14b as an active chat/generation model is superseded — see `MASTER_SYSTEM_DOCUMENTATION.md` §12.

**Date:** 2026-05-08 | **Ollama:** 0.20.6 | **GPU:** Intel Arc Pro B50 (BMG G21)

## Hardware

- **GPU:** Intel Arc Pro B50 Graphics (BMG G21)
- **PCI:** 03:00.0
- **VRAM:** Shared (UMA) — uses system RAM via Vulkan
- **Driver:** Intel open-source Mesa (Vulkan 1.4.318, driver 25.2.8)

## Prerequisites (already installed)

```
intel-opencl-icd                 26.09.37435.12
libze-intel-gpu1                 26.09.37435.12
intel-oneapi-dnnl-2026.0         2026.0.0-688
intel-media-va-driver-non-free   25.2.3
```

Level-zero libs at `/usr/lib/x86_64-linux-gnu/libze_intel_gpu.so.1`
Vulkan backend at `/usr/local/lib/ollama/vulkan/libggml-vulkan.so`

## Configuration

### Systemd override (survives reboot)

File: `/etc/systemd/system/ollama.service.d/override.conf`

```ini
[Service]
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_VULKAN=1"
Environment="OLLAMA_NUM_GPU=-1"
```

| Variable | Purpose |
|----------|---------|
| `OLLAMA_VULKAN=1` | Enable experimental Vulkan backend (required for Intel Arc on Ollama 0.20.6) |
| `OLLAMA_NUM_GPU=-1` | Offload ALL model layers to GPU (-1 = all) |
| `OLLAMA_KEEP_ALIVE=-1` | Keep model loaded in memory forever (no unload timeout) |

### Apply changes

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

### Verify GPU is active

```bash
# Check layers offloaded
journalctl -u ollama --no-pager -n 25 | grep -i "offload\|vulkan\|layer"

# Expected output:
# ggml_vulkan: Found 1 Vulkan devices:
# ggml_vulkan: 0 = Intel(R) Arc(tm) Pro B50 Graphics (BMG G21)
# loaded Vulkan backend from /usr/local/lib/ollama/vulkan/libggml-vulkan.so
# offloading 40 repeating layers to GPU
# offloading output layer to GPU
# offloaded 41/41 layers to GPU
# model weights device=Vulkan0 size="8.2 GiB"

# Check VRAM allocation
curl -s http://localhost:11434/api/ps | python3 -c "
import sys,json
d = json.load(sys.stdin)
for m in d.get('models', []):
    print(f\"{m['name']}: {m.get('size_vram',0)/1e9:.1f}GB VRAM\")
"
```

## Performance (qwen3:14b Q4_K_M)

| Mode | Inference Time | Status |
|------|---------------|--------|
| CPU only (0 GPU layers) | ~300s (timeout) | Unusable |
| GPU Vulkan (41/41 layers) | ~15s per chunk | Production |
| First inference after restart | ~80s (shader compilation) | Normal |

## Troubleshooting

### "experimental Vulkan support disabled"
Missing `OLLAMA_VULKAN=1`. Check override:
```bash
systemctl show ollama.service | grep Environment
```

### "offloaded 0/41 layers to GPU"
- Wrong env var name (e.g., `OLLAMA_INTEL_GPU` is deprecated, use `OLLAMA_VULKAN`)
- Override file has leading spaces (systemd ignores malformed lines silently)
- Check: `cat -A /etc/systemd/system/ollama.service.d/override.conf`

### Slow first inference (~80s)
Normal — Vulkan shader compilation on first use. Subsequent calls are ~15s.
Use `warmup_ollama()` before batch processing.

### Multiple processes competing for GPU
The toll gate in `local_llm.py` uses `fcntl.flock()` on `/tmp/ollama_llm_gate.lock`.
Only one process hits Ollama at a time. Others queue.

## Backup

The override file is backed up by `scripts/full_system_backup.py` as `systemd/ollama_override.conf`.

### Restore after bare metal rebuild

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d/
sudo cp systemd/ollama_override.conf /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart ollama
```
