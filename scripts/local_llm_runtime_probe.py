#!/usr/bin/env python3
"""local_llm_runtime_probe.py — ratify the local-LLM runtime against config/local_llm_runtime_policy.yaml.

Reports: visible GPUs, whether inference is pinned to the discrete Arc Pro B50 (not integrated Iris Xe),
resident model, backend (Vulkan/SYCL/oneAPI/IPEX/unknown), and policy violations (missing
GGML_VK_VISIBLE_DEVICES, integrated selected, 27B/31B resident during market hours, embed evicted).
Read-only. No broker writes.

    python3 scripts/local_llm_runtime_probe.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config" / "local_llm_runtime_policy.yaml"


def _sh(cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def _in_market_window() -> bool:
    try:
        from zoneinfo import ZoneInfo
        et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        et = datetime.now()
    return et.weekday() < 5 and "06:00" <= et.strftime("%H:%M") < "12:00"


def probe() -> dict:
    pol = yaml.safe_load(POLICY.read_text())
    findings = []

    # 1. visible GPUs
    vk = _sh(["vulkaninfo", "--summary"])
    gpus = re.findall(r"deviceName\s*=\s*(.+)", vk)
    has_discrete = any("Arc" in g for g in gpus)
    has_integrated = any("Iris Xe" in g for g in gpus)

    # 2. llama-server backend + device pin (from cmdline/env of any running llama-server)
    psout = _sh(["ps", "-eo", "args"])
    llama_line = next((l for l in psout.splitlines() if "llama-server" in l and "grep" not in l), "")
    backend = "unknown"
    if "vulkan" in llama_line.lower() or "llama-cpp-vulkan" in llama_line:
        backend = "vulkan"
    elif "sycl" in llama_line.lower():
        backend = "sycl_oneapi"
    elif "ipex" in llama_line.lower():
        backend = "ipex_llm"
    # env pin (best-effort: from the process environ if accessible, else from our own env)
    vk_dev = os.getenv("GGML_VK_VISIBLE_DEVICES")
    llama_pid = None
    m = re.search(r"llama-server", psout)
    try:
        for pid in _sh(["pgrep", "-f", "llama-server"]).split():
            envf = Path(f"/proc/{pid.strip()}/environ")
            if envf.exists():
                env = envf.read_text(errors="replace")
                mm = re.search(r"GGML_VK_VISIBLE_DEVICES=([^\x00]*)", env)
                if mm:
                    vk_dev = mm.group(1)
                llama_pid = pid.strip()
                break
    except Exception:
        pass

    # 3. resident model (ollama)
    ops = _sh(["ollama", "ps"])
    resident = [ln.split()[0] for ln in ops.splitlines()[1:] if ln.strip()]

    # 4. policy violations
    market = _in_market_window()
    blocked = {b["model"] for b in pol.get("blocked_market_hour_models", [])}
    if backend == "vulkan" and not vk_dev:
        findings.append({"severity": "warning", "type": "vulkan_device_not_pinned",
                         "message": "GGML_VK_VISIBLE_DEVICES not set for the Vulkan path — risk of landing on integrated Iris Xe"})
    if vk_dev == "0":
        findings.append({"severity": "critical", "type": "integrated_gpu_selected",
                         "message": "GGML_VK_VISIBLE_DEVICES=0 → integrated Iris Xe selected for LLM generation (not allowed)"})
    for mdl in resident:
        if mdl in blocked and market:
            findings.append({"severity": "critical", "type": "blocked_model_resident_market",
                             "message": f"{mdl} (blocked) resident during 06:00-12:00 ET market window"})

    # embed health (timeout-rate proxy from rag log)
    embed_timeouts = 0
    try:
        log = ROOT / "logs" / "watchlist_agent_jobs.log"
        if log.exists():
            today = datetime.now().strftime("%Y-%m-%d")
            embed_timeouts = sum(1 for l in log.read_text(errors="replace").splitlines()[-3000:]
                                 if today in l and "11434" in l and "timed out" in l.lower())
        if embed_timeouts >= 10:
            findings.append({"severity": "warning", "type": "embed_timeouts",
                             "message": f"{embed_timeouts} nomic-embed-text timeouts today — embed lane under contention"})
    except Exception:
        pass

    device_selected = ("discrete_arc_b50" if vk_dev == "1" else
                       "integrated_iris_xe" if vk_dev == "0" else
                       "unpinned_default" if backend == "vulkan" else "n/a")
    return {
        "ok": not any(f["severity"] == "critical" for f in findings),
        "status": "PASS" if not findings else ("FAIL" if any(f["severity"] == "critical" for f in findings) else "WARN"),
        "generated_at": datetime.now().isoformat(),
        "market_window": market,
        "visible_gpus": gpus, "has_discrete_arc_b50": has_discrete, "has_integrated_iris_xe": has_integrated,
        "backend": backend, "ggml_vk_visible_devices": vk_dev, "device_selected": device_selected,
        "resident_models": resident, "llama_server_pid": llama_pid,
        "production_model": "gemma3:12b", "fast_model": "gemma3:4b", "embed_model": "nomic-embed-text",
        "blocked_market_models": sorted(blocked), "embed_timeouts_today": embed_timeouts,
        "findings": findings,
        "note": "Read-only runtime ratification. Pin to the discrete Arc Pro B50 (GGML_VK_VISIBLE_DEVICES=1); "
                "27B/31B blocked locally in market hours; no paid/local-31B fallback. No broker writes.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = probe()
    print(json.dumps(r, indent=2, default=str) if args.json else
          f"runtime: {r['status']} backend={r['backend']} device={r['device_selected']} resident={r['resident_models']} findings={len(r['findings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
