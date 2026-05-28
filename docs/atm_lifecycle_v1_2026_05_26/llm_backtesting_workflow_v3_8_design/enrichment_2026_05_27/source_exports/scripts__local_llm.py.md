# Source: scripts/local_llm.py (13043 bytes)
```python
"""
local_llm.py — Local Ollama LLM with cloud fallback + toll gate queue.
Use for non-time-sensitive narrative generation to save API costs.

All callers go through generate() which acquires a file lock before
hitting Ollama, preventing concurrent GPU contention.

Usage:
    from local_llm import generate

    text = generate(prompt, timeout=300)
    # Returns text from Ollama if available, falls back to Claude Sonnet
"""
import fcntl
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from local_llm_config import get_local_llm_model, get_local_llm_base_url, apply_ollama_runtime_env

apply_ollama_runtime_env()

OLLAMA_URL = get_local_llm_base_url().rstrip("/") + "/api/chat"
OLLAMA_MODEL_FAST = get_local_llm_model()
OLLAMA_MODEL = get_local_llm_model()
# Fallback models — centralized from .env, live-discovered defaults
FALLBACK_OPENAI = os.getenv("LLM_FALLBACK_OPENAI", "gpt-4o-mini").strip()
FALLBACK_ANTHROPIC = os.getenv("LLM_FALLBACK_ANTHROPIC", "claude-sonnet-4-6").strip()
DEFAULT_TIMEOUT = 300
LOCK_FILE = Path("/tmp/ollama_llm_gate.lock")
LOCK_WAIT_TIMEOUT = 600  # max seconds to wait for lock

model_used = None  # tracks which model last responded

# ── LLM Fleet v4.1 — JSONL Audit Logging ─────────────────────────────────
_AUDIT_LOG = Path(__file__).resolve().parent.parent / "logs" / "llm_routing_audit.jsonl"


def _log_audit(caller: str, process_type: str, model: str, provider: str,
               latency_ms: int, status: str, fallback_used: bool = False):
    """Append one audit line to JSONL. Non-blocking, never raises."""
    try:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "caller": caller,
            "process_type": process_type,
            "model": model,
            "provider": provider,
            "latency_ms": latency_ms,
            "status": status,
            "fallback": fallback_used,
            "phase": os.getenv("LLM_DEPLOYMENT_PHASE", ""),
        }
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # audit must never break callers


# ── Toll gate: file-based lock so only one caller uses Ollama at a time ──

class _OllamaGate:
    """File lock that serializes all Ollama access across processes."""

    def __init__(self):
        self._fd = None

    def acquire(self, wait_timeout: int = LOCK_WAIT_TIMEOUT) -> bool:
        """Acquire exclusive lock. Blocks up to wait_timeout seconds."""
        try:
            self._fd = open(LOCK_FILE, "w")
            deadline = time.monotonic() + wait_timeout
            while True:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Write PID for debugging
                    self._fd.seek(0)
                    self._fd.truncate()
                    self._fd.write(f"{os.getpid()} {time.strftime('%H:%M:%S')}\n")
                    self._fd.flush()
                    return True
                except (IOError, OSError):
                    if time.monotonic() >= deadline:
                        print(f"  [local-llm] Gate timeout — waited {wait_timeout}s for lock")
                        self._fd.close()
                        self._fd = None
                        return False
                    time.sleep(2)
        except Exception as e:
            print(f"  [local-llm] Gate error: {e}")
            return False

    def release(self):
        """Release the lock."""
        if self._fd:
```
