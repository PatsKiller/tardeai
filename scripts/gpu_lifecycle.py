#!/usr/bin/env python3
"""gpu_lifecycle.py — GPU lifecycle management for LLM Fleet v4.1.

Provides warmup, cooldown, status, OOM detection, and active-hours gating.
Safe to call when Ollama/GPU is unavailable — fails gracefully with "unknown" status.

Usage:
    .venv/bin/python scripts/gpu_lifecycle.py status
    .venv/bin/python scripts/gpu_lifecycle.py warmup gemma3:4b
    .venv/bin/python scripts/gpu_lifecycle.py cooldown gemma3:4b
    .venv/bin/python scripts/gpu_lifecycle.py check_oom
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

OLLAMA_BASE = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434").strip()
VRAM_TOTAL_GB = 16.0  # Intel Arc Pro B50
VRAM_HEADROOM_GB = float(os.getenv("LLM_VRAM_HEADROOM_GB", "0.5"))
WARMUP_TIMEOUT = int(os.getenv("LLM_WARMUP_TIMEOUT_SEC", "90"))
OOM_LOG = ROOT / "logs" / "gpu_oom.log"
WARMUP_LOG = ROOT / "logs" / "gpu_warmup.log"


class GPULifecycleError(Exception):
    pass


def _ollama_request(path: str, data: dict = None, timeout: int = 10) -> dict:
    """Make a request to Ollama API. Returns parsed JSON or error dict."""
    url = f"{OLLAMA_BASE}{path}"
    try:
        if data:
            req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": f"Ollama unreachable: {e}"}
    except TimeoutError:
        return {"error": f"Ollama timeout after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}


def status() -> dict:
    """Return current GPU/Ollama state. Never raises."""
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ollama_alive": False,
        "resident_models": [],
        "vram_used_gb": 0,
        "vram_free_gb": VRAM_TOTAL_GB,
        "vram_total_gb": VRAM_TOTAL_GB,
        "active_hours": is_active_hours(),
        "active_hours_override": _truthy(os.getenv("LLM_OVERRIDE_ACTIVE_HOURS")),
        "last_oom_event": _last_oom_event(),
        "deployment_phase": os.getenv("LLM_DEPLOYMENT_PHASE", ""),
    }

    ps = _ollama_request("/api/ps", timeout=5)
    if "error" not in ps:
        result["ollama_alive"] = True
        models = []
        total_vram = 0
        for m in ps.get("models", []):
            size_gb = round(m.get("size", 0) / 1024 / 1024 / 1024, 2)
            total_vram += size_gb
            models.append({"name": m["name"], "vram_gb": size_gb})
        result["resident_models"] = models
        result["vram_used_gb"] = round(total_vram, 2)
        result["vram_free_gb"] = round(VRAM_TOTAL_GB - total_vram, 2)
    else:
        result["ollama_error"] = ps["error"]

    return result


def warmup(model: str, timeout: int = None) -> dict:
    """Ensure model is resident in VRAM. Returns load result."""
    timeout = timeout or WARMUP_TIMEOUT
    t0 = time.time()

    # Quick check if already loaded
    ps = _ollama_request("/api/ps", timeout=5)
    if "error" not in ps:
        for m in ps.get("models", []):
            if m.get("name", "").startswith(model.split(":")[0]):
                elapsed = int((time.time() - t0) * 1000)
                _log_warmup(model, True, elapsed, "already_resident")
                return {"model": model, "was_resident": True, "load_time_ms": elapsed, "status": "ok"}

    # Load the model with a minimal prompt
    resp = _ollama_request("/api/chat", data={
        "model": model, "stream": False,
        "messages": [{"role": "user", "content": "ready"}],
        "options": {"num_predict": 1},
    }, timeout=timeout)

    elapsed = int((time.time() - t0) * 1000)

    if "error" in resp:
        _log_warmup(model, False, elapsed, resp["error"])
        _alert_warmup_failure(model, resp["error"])
        return {"model": model, "was_resident": False, "load_time_ms": elapsed,
                "status": "failed", "error": resp["error"]}

    _log_warmup(model, True, elapsed, "loaded")
    return {"model": model, "was_resident": False, "load_time_ms": elapsed, "status": "ok"}


def cooldown(model: str = None) -> dict:
    """Unload model from VRAM. If None, unload all."""
    if model:
        resp = _ollama_request("/api/chat", data={
            "model": model, "keep_alive": 0,
            "messages": [{"role": "user", "content": ""}],
            "options": {"num_predict": 0},
        }, timeout=15)
        return {"model": model, "status": "unloaded" if "error" not in resp else "failed"}
    else:
        ps = _ollama_request("/api/ps", timeout=5)
        if "error" in ps:
            return {"status": "failed", "error": ps["error"]}
        for m in ps.get("models", []):
            cooldown(m["name"])
        return {"status": "all_unloaded"}


def can_load(model_size_gb: float, current_resident: list = None) -> bool:
    """Check if a model fits in VRAM with headroom."""
    if current_resident is None:
        s = status()
        used = s["vram_used_gb"]
    else:
        used = sum(m.get("vram_gb", 0) for m in current_resident)
    return (VRAM_TOTAL_GB - used - model_size_gb) >= VRAM_HEADROOM_GB


def is_active_hours() -> bool:
    """True during 9:30 AM - 4:00 PM ET on weekdays."""
    try:
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    return market_open <= now <= market_close


def gate_batch_overnight() -> None:
    """Refuse BATCH_OVERNIGHT during active hours unless override is set."""
    if is_active_hours() and not _truthy(os.getenv("LLM_OVERRIDE_ACTIVE_HOURS")):
        raise GPULifecycleError(
            "BATCH_OVERNIGHT blocked during active hours (9:30-16:00 ET). "
            "Set LLM_OVERRIDE_ACTIVE_HOURS=true for one-shot testing."
        )


def check_oom() -> dict:
    """Check Ollama logs for recent OOM events. Returns summary."""
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "oom_detected": False, "events": []}
    try:
        import subprocess
        proc = subprocess.run(
            ["journalctl", "-u", "ollama.service", "--since", "5 min ago", "--no-pager", "-q"],
            capture_output=True, text=True, timeout=10
        )
        lines = proc.stdout.lower()
        oom_keywords = ["out of memory", "oom", "vram", "allocation failed", "memory allocation"]
        for kw in oom_keywords:
            if kw in lines:
                result["oom_detected"] = True
                result["events"].append({"keyword": kw, "source": "journalctl"})
    except Exception as e:
        result["check_error"] = str(e)

    if result["oom_detected"]:
        _log_oom(result)
        _alert_oom(result)

    return result


@contextmanager
def daytime_test(test_model: str):
    """Context manager for testing during active hours. Requires override flag."""
    if not _truthy(os.getenv("LLM_OVERRIDE_ACTIVE_HOURS")):
        raise GPULifecycleError("daytime_test requires LLM_OVERRIDE_ACTIVE_HOURS=true")

    snapshot = status()
    previously_resident = [m["name"] for m in snapshot.get("resident_models", [])]
    t0 = time.time()

    try:
        cooldown()
        warmup(test_model)
        yield
    finally:
        cooldown(test_model)
        for model in previously_resident:
            warmup(model)


# ── Internal helpers ──────────────────────────────────────────────────────

def _truthy(val) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def _last_oom_event() -> str | None:
    try:
        if OOM_LOG.exists():
            lines = OOM_LOG.read_text().strip().splitlines()
            for line in reversed(lines):
                try:
                    entry = json.loads(line)
                    if entry.get("oom_detected"):
                        return entry.get("checked_at")
                except Exception:
                    pass
    except Exception:
        pass
    return None


def _log_warmup(model: str, success: bool, elapsed_ms: int, detail: str):
    try:
        WARMUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "model": model,
                 "success": success, "elapsed_ms": elapsed_ms, "detail": detail}
        with open(WARMUP_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _log_oom(result: dict):
    try:
        OOM_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(OOM_LOG, "a") as f:
            f.write(json.dumps(result) + "\n")
    except Exception:
        pass


def _alert_warmup_failure(model: str, error: str):
    try:
        from alert_dispatcher import dispatch_alert
        dispatch_alert(
            alert_type="LLM_WARMUP_FAILED", symbol="",
            title=f"LLM Warmup Failed: {model}",
            body=f"GPU lifecycle warmup failed for {model}: {error}",
            tier="ALERT", source="gpu_lifecycle",
            dedupe_scope="global",
        )
    except Exception:
        pass


def _alert_oom(result: dict):
    try:
        from alert_dispatcher import dispatch_alert
        dispatch_alert(
            alert_type="GPU_OOM", symbol="",
            title="GPU OOM Detected",
            body=f"OOM event detected in Ollama logs: {result.get('events', [])}",
            tier="URGENT", source="gpu_lifecycle",
            dedupe_scope="global",
        )
    except Exception:
        pass


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GPU Lifecycle Manager")
    parser.add_argument("command", choices=["status", "warmup", "cooldown", "check_oom", "vram_swap_test"],
                        help="Lifecycle command")
    parser.add_argument("model", nargs="?", default=None, help="Model name (for warmup/cooldown)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.command == "status":
        result = status()
    elif args.command == "warmup":
        if not args.model:
            parser.error("warmup requires a model name")
        result = warmup(args.model)
    elif args.command == "cooldown":
        result = cooldown(args.model)
    elif args.command == "check_oom":
        result = check_oom()
    elif args.command == "vram_swap_test":
        s = status()
        result = {"resident_before": s["resident_models"], "vram_before": s["vram_used_gb"]}
        print("VRAM swap test — manual execution required for actual model swap")

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        for k, v in result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
