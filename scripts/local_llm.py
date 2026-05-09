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
FALLBACK_OPENAI = "gpt-4o-mini"
FALLBACK_ANTHROPIC = "claude-sonnet-4-6"
DEFAULT_TIMEOUT = 300
LOCK_FILE = Path("/tmp/ollama_llm_gate.lock")
LOCK_WAIT_TIMEOUT = 600  # max seconds to wait for lock

model_used = None  # tracks which model last responded


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
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
            except Exception:
                pass
            self._fd = None


_gate = _OllamaGate()


def warmup_ollama(model: str = None, timeout: int = 480) -> bool:
    """Ping Ollama to ensure model is loaded before batch analysis.
    Default 480s (8 min) to handle cold GPU model load.
    Acquires the gate lock to prevent contention."""
    model = model or OLLAMA_MODEL
    if not _gate.acquire():
        print("  [local-llm] Warmup skipped — could not acquire gate")
        return False
    try:
        payload = json.dumps({
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": "ready"}],
            "think": False,
            "options": {"num_predict": 5}
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            print(f"  [local-llm] Ollama warmup OK — model {model} loaded")
            return True
    except Exception as e:
        print(f"  [local-llm] Ollama warmup failed: {e}")
        return False
    finally:
        _gate.release()


def _try_ollama(prompt: str, timeout: int, model: str = OLLAMA_MODEL,
                retries: int = 1) -> str | None:
    """Try Ollama with retry logic. Returns text or None on failure/timeout.
    Caller must hold the gate lock."""
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "think": False,
        "options": {"temperature": 0.3, "num_predict": 300}
    }).encode()

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
                text = data.get("message", {}).get("content", "").strip()
                duration = round(data.get("total_duration", 0) / 1e9, 1)
                tokens = data.get("eval_count", 0)
                print(f"  [local-llm] Ollama OK — {duration}s, {tokens} tokens")
                return text if text else None
        except urllib.error.URLError as e:
            print(f"  [local-llm] Ollama unavailable: {e}")
            return None  # no point retrying if server is down
        except TimeoutError:
            print(f"  [local-llm] Ollama timeout after {timeout}s "
                  f"(attempt {attempt+1}/{retries+1})")
            if attempt < retries:
                time.sleep(5)
                continue
            return None
        except Exception as e:
            print(f"  [local-llm] Ollama error: {e} "
                  f"(attempt {attempt+1}/{retries+1})")
            if attempt < retries:
                time.sleep(3)
                continue
            return None
    return None


def _try_openai(prompt: str) -> str | None:
    """Fallback to OpenAI gpt-4o-mini."""
    try:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("OPENAI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"')
                        break
        if not api_key:
            return None
        payload = json.dumps({
            "model": FALLBACK_OPENAI,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()
            print(f"  [local-llm] OpenAI fallback OK — {len(text)} chars")
            return text
    except Exception as e:
        print(f"  [local-llm] OpenAI fallback error: {e}")
        return None


def _try_anthropic(prompt: str) -> str | None:
    """Final fallback to Claude Sonnet via Anthropic API."""
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("ANTHROPIC_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"')
                        break
        if not api_key:
            print("  [local-llm] No Anthropic key found")
            return None

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=FALLBACK_ANTHROPIC,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip()
        print(f"  [local-llm] Anthropic fallback OK — {len(text)} chars")
        return text
    except Exception as e:
        print(f"  [local-llm] Anthropic fallback error: {e}")
        return None


def generate(prompt: str, timeout: int = DEFAULT_TIMEOUT,
             fallback: bool = True, fast: bool = True) -> str:
    """4-tier chain with toll gate: local model -> OpenAI -> Anthropic.
    Acquires file lock before Ollama calls to prevent GPU contention."""
    global model_used
    model_used = None

    # Acquire toll gate — only one process hits Ollama at a time
    if not _gate.acquire():
        print("  [local-llm] Could not acquire gate — skipping Ollama, trying fallbacks")
        if fallback:
            result = _try_openai(prompt)
            if result:
                model_used = FALLBACK_OPENAI
                return result
            result = _try_anthropic(prompt)
            if result:
                model_used = FALLBACK_ANTHROPIC
                return result
        return ""

    try:
        # Tier 1: local model (fast)
        if fast:
            result = _try_ollama(prompt, min(timeout, 30), model=OLLAMA_MODEL_FAST)
            if result:
                model_used = OLLAMA_MODEL_FAST
                return result
        # Tier 2: local model (full) with retry
        result = _try_ollama(prompt, timeout, model=OLLAMA_MODEL, retries=1)
        if result:
            model_used = OLLAMA_MODEL
            return result
    finally:
        _gate.release()

    # Cloud fallbacks don't need the gate
    if fallback:
        print(f"  [local-llm] Using OpenAI fallback ({FALLBACK_OPENAI})")
        result = _try_openai(prompt)
        if result:
            model_used = FALLBACK_OPENAI
            return result

    if fallback:
        print(f"  [local-llm] Using Anthropic fallback ({FALLBACK_ANTHROPIC})")
        result = _try_anthropic(prompt)
        if result:
            model_used = FALLBACK_ANTHROPIC
            return result

    print("  [local-llm] All LLM attempts failed — returning empty")
    return ""


if __name__ == "__main__":
    # Quick test
    test = generate(
        "Say 'local LLM working' and nothing else.",
        timeout=30
    )
    print(f"Test result: {test}")
