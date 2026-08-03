"""
local_llm.py — Local Ollama LLM with DeepSeek Flash PRIMARY + cloud fallback + toll gate queue.

DeepSeek Flash is the PRIMARY model (fast, cheap, reliable API).
Local gemma3:4b is the FALLBACK (when DeepSeek is unavailable or for offline operation).
Paid OpenAI/Anthropic fallbacks are gated behind ALLOW_PAID_FALLBACK=true (default: false).

All callers go through generate() which tries DeepSeek first, then local Ollama, then
paid cloud only if explicitly allowed.

Safety router (2026-05-28):
- Blocks disabled models (DISABLED_LOCAL_LLM_MODELS)
- Forces CPU mode when FORCE_LOCAL_LLM_CPU=true
- Pre-call cleanup: unloads blocked/stale models
- JSONL safety audit log

Usage:
    from local_llm import generate

    text = generate(prompt, timeout=300)
    # Returns text from DeepSeek Flash if available, falls back to Ollama gemma3:4b
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

# ── DeepSeek Flash (PRIMARY API) ──
_DEEPSEEK_API_KEY = os.environ.get("deepseek_tradeai", "").strip()
_DEEPSEEK_FLASH_URL = "https://api.deepseek.com/v1/chat/completions"
_DEEPSEEK_FLASH_MODEL = "deepseek-v4-flash"
_DEEPSEEK_FLASH_TIMEOUT = int(os.environ.get("DEEPSEEK_FLASH_TIMEOUT", "30"))

OLLAMA_BASE = get_local_llm_base_url().rstrip("/")
OLLAMA_URL = OLLAMA_BASE + "/api/chat"
OLLAMA_MODEL_FAST = get_local_llm_model()
OLLAMA_MODEL = get_local_llm_model()
# Paid fallback models — gated behind ALLOW_PAID_FALLBACK=true
FALLBACK_OPENAI = os.getenv("LLM_FALLBACK_OPENAI", "gpt-4o-mini").strip()
FALLBACK_ANTHROPIC = os.getenv("LLM_FALLBACK_ANTHROPIC", "claude-sonnet-4-6").strip()
ALLOW_PAID_FALLBACK = os.getenv("ALLOW_PAID_FALLBACK", "false").strip().lower() in ("1", "true", "yes", "on")
DEFAULT_TIMEOUT = 300
LOCK_FILE = Path("/tmp/tradeai_local_llm_single_job.lock")
LOCK_WAIT_TIMEOUT = 600  # max seconds to wait for lock

model_used = None  # tracks which model last responded

# ── Safety: disabled models & CPU enforcement ────────────────────────────
DISABLED_MODELS = set(
    m.strip() for m in os.getenv("DISABLED_LOCAL_LLM_MODELS", "").split(",") if m.strip()
)
SAFE_MODEL = os.getenv("LOCAL_LLM_SAFE_MODEL", "gemma3:4b").strip()
FORCE_CPU = os.getenv("FORCE_LOCAL_LLM_CPU", "false").strip().lower() in {"1", "true", "yes", "on"}
FORCE_NUM_GPU = int(os.getenv("LOCAL_LLM_NUM_GPU", "99"))  # 99 = use default

# ── LLM Fleet v4.1 — JSONL Audit Logging ─────────────────────────────────
_AUDIT_LOG = Path(__file__).resolve().parent.parent / "logs" / "llm_routing_audit.jsonl"
_SAFETY_LOG = Path(__file__).resolve().parent.parent / "logs" / "llm_router_safety.jsonl"


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


def _log_safety(caller: str, requested_model: str, resolved_model: str,
                disabled_blocked: bool, force_cpu: bool, num_gpu: int,
                duration_ms: int, status: str, error: str = "",
                loaded_before: list = None, loaded_after: list = None):
    """Append one safety audit line. Non-blocking, never raises."""
    try:
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "caller": caller,
            "requested_model": requested_model,
            "resolved_model": resolved_model,
            "disabled_model_blocked": disabled_blocked,
            "force_cpu": force_cpu,
            "num_gpu": num_gpu,
            "duration_ms": duration_ms,
            "status": status,
            "error": error,
            "loaded_models_before": loaded_before or [],
            "loaded_models_after": loaded_after or [],
        }
        _SAFETY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_SAFETY_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _resolve_model(requested: str) -> tuple[str, bool]:
    """Resolve model, blocking disabled models. Returns (model, was_blocked)."""
    if requested in DISABLED_MODELS:
        print(f"  [local-llm] BLOCKED disabled model {requested} → substituting {SAFE_MODEL}")
        return SAFE_MODEL, True
    return requested, False


def _get_loaded_models() -> list[str]:
    """Query Ollama /api/ps for currently loaded model names."""
    try:
        ps_url = OLLAMA_BASE + "/api/ps"
        req = urllib.request.Request(ps_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def _unload_model(name: str) -> bool:
    """Unload a specific model via /api/generate keep_alive=0."""
    try:
        gen_url = OLLAMA_BASE + "/api/generate"
        payload = json.dumps({"model": name, "keep_alive": 0, "prompt": ""}).encode()
        req = urllib.request.Request(gen_url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10)
        print(f"  [local-llm] Unloaded {name}")
        return True
    except Exception as e:
        print(f"  [local-llm] Failed to unload {name}: {e}")
        return False


def _pre_call_cleanup(target_model: str):
    """Unload disabled models and non-target generation models before calling."""
    loaded = _get_loaded_models()
    for m in loaded:
        if m in DISABLED_MODELS:
            _unload_model(m)
        elif m != target_model and "embed" not in m.lower():
            _unload_model(m)
    # Verify disabled models are gone
    still_loaded = _get_loaded_models()
    for m in still_loaded:
        if m in DISABLED_MODELS:
            print(f"  [local-llm] FAIL CLOSED: disabled model {m} still loaded after cleanup")
            return False
    return True


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
    Acquires the gate lock to prevent contention.
    Respects disabled model list and CPU enforcement."""
    model = model or OLLAMA_MODEL
    resolved, was_blocked = _resolve_model(model)
    if not _gate.acquire():
        print("  [local-llm] Warmup skipped — could not acquire gate")
        return False
    try:
        _pre_call_cleanup(resolved)
        options = {"num_predict": 5}
        if FORCE_CPU:
            options["num_gpu"] = 0
        payload = json.dumps({
            "model": resolved,
            "stream": False,
            "messages": [{"role": "user", "content": "ready"}],
            "think": False,
            "options": options
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            print(f"  [local-llm] Ollama warmup OK — model {resolved} loaded"
                  + (f" (blocked {model})" if was_blocked else ""))
            return True
    except Exception as e:
        print(f"  [local-llm] Ollama warmup failed: {e}")
        return False
    finally:
        _gate.release()


def _ensure_vram_clear(keep_model: str = None):
    """Unload all models except the one we're about to use. Prevents VRAM overcommit.
    Uses safety-aware _pre_call_cleanup."""
    _pre_call_cleanup(keep_model or OLLAMA_MODEL)


def _try_ollama(prompt: str, timeout: int, model: str = OLLAMA_MODEL,
                retries: int = 1, caller: str = "") -> str | None:
    """Try Ollama with retry logic and safety router.
    Blocks disabled models, forces CPU when configured.
    Caller must hold the gate lock."""
    t0 = time.time()
    loaded_before = _get_loaded_models()

    # Resolve model — block disabled
    resolved, was_blocked = _resolve_model(model)

    # Pre-call cleanup
    if not _pre_call_cleanup(resolved):
        _log_safety(caller, model, resolved, was_blocked, FORCE_CPU,
                     0, int((time.time() - t0) * 1000), "fail_closed_disabled_loaded",
                     loaded_before=loaded_before, loaded_after=_get_loaded_models())
        return None

    # Build options with CPU enforcement. num_predict env-overridable (2026-06-12: the 300 cap
    # truncated strict-JSON outputs like entry plans mid-object — callers needing longer output set
    # LOCAL_LLM_NUM_PREDICT for their process; default unchanged for all existing callers).
    options = {"temperature": 0.3, "num_predict": int(os.getenv("LOCAL_LLM_NUM_PREDICT", "300"))}
    if FORCE_CPU:
        options["num_gpu"] = 0
    elif FORCE_NUM_GPU != 99:
        options["num_gpu"] = FORCE_NUM_GPU

    payload = json.dumps({
        "model": resolved,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "think": False,
        "options": options
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
                print(f"  [local-llm] Ollama OK — {resolved} {duration}s, {tokens} tokens"
                      + (f" (blocked {model})" if was_blocked else ""))
                _log_safety(caller, model, resolved, was_blocked, FORCE_CPU,
                             options.get("num_gpu", -1),
                             int((time.time() - t0) * 1000), "ok",
                             loaded_before=loaded_before, loaded_after=_get_loaded_models())
                return text if text else None
        except urllib.error.URLError as e:
            print(f"  [local-llm] Ollama unavailable: {e}")
            _log_safety(caller, model, resolved, was_blocked, FORCE_CPU,
                         options.get("num_gpu", -1),
                         int((time.time() - t0) * 1000), "unavailable", str(e),
                         loaded_before=loaded_before, loaded_after=_get_loaded_models())
            return None
        except TimeoutError:
            print(f"  [local-llm] Ollama timeout after {timeout}s "
                  f"(attempt {attempt+1}/{retries+1})")
            if attempt < retries:
                time.sleep(5)
                continue
            _log_safety(caller, model, resolved, was_blocked, FORCE_CPU,
                         options.get("num_gpu", -1),
                         int((time.time() - t0) * 1000), "timeout", f"{timeout}s",
                         loaded_before=loaded_before, loaded_after=_get_loaded_models())
            return None
        except Exception as e:
            print(f"  [local-llm] Ollama error: {e} "
                  f"(attempt {attempt+1}/{retries+1})")
            if attempt < retries:
                time.sleep(3)
                continue
            _log_safety(caller, model, resolved, was_blocked, FORCE_CPU,
                         options.get("num_gpu", -1),
                         int((time.time() - t0) * 1000), "error", str(e),
                         loaded_before=loaded_before, loaded_after=_get_loaded_models())
            return None
    return None


def _try_deepseek_flash(prompt: str, timeout: int = None) -> str | None:
    """PRIMARY: DeepSeek Flash API. Falls back to local gemma on failure."""
    if not _DEEPSEEK_API_KEY:
        return None
    import urllib.request as _rq
    timeout_s = timeout or _DEEPSEEK_FLASH_TIMEOUT
    try:
        payload = json.dumps({
            "model": _DEEPSEEK_FLASH_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2048
        }).encode()
        req = _rq.Request(
            _DEEPSEEK_FLASH_URL,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {_DEEPSEEK_API_KEY}"},
            method="POST"
        )
        with _rq.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage") or {}
            print(f"  [local-llm] DeepSeek Flash OK — {len(text)} chars, "
                  f"{usage.get('prompt_tokens',0)} in / {usage.get('completion_tokens',0)} out")
            return text
    except Exception as e:
        print(f"  [local-llm] DeepSeek Flash failed: {e} — falling back to local gemma")
        return None


def _try_openai(prompt: str) -> str | None:
    """Fallback to OpenAI gpt-4o-mini (only if ALLOW_PAID_FALLBACK=true)."""
    if not ALLOW_PAID_FALLBACK:
        return None
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
    """Final fallback to Claude Sonnet via Anthropic API (only if ALLOW_PAID_FALLBACK=true)."""
    if not ALLOW_PAID_FALLBACK:
        return None
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
             fallback: bool = True, fast: bool = True,
             caller: str = "", process_type: str = "STANDARD") -> str:
    """4-tier chain: DeepSeek Flash (PRIMARY) -> local gemma -> OpenAI -> Anthropic.
    Paid OpenAI/Anthropic fallbacks are gated behind ALLOW_PAID_FALLBACK=true.

    Args:
        caller: script name for audit logging (optional)
        process_type: LLM fleet process type for audit (optional)
    """
    global model_used
    model_used = None
    t0 = time.time()

    # Tier 0: DeepSeek Flash (PRIMARY — no file lock needed for API call)
    result = _try_deepseek_flash(prompt, timeout=min(timeout, _DEEPSEEK_FLASH_TIMEOUT))
    if result:
        model_used = _DEEPSEEK_FLASH_MODEL
        _log_audit(caller, process_type, _DEEPSEEK_FLASH_MODEL, "deepseek",
                   int((time.time()-t0)*1000), "ok")
        return result

    # Tier 1-2: local Ollama (needs file lock)
    if not _gate.acquire():
        print("  [local-llm] Could not acquire gate — skipping Ollama, trying fallbacks")
        _log_audit(caller, process_type, OLLAMA_MODEL, "ollama", 0, "gate_timeout")
        if fallback and ALLOW_PAID_FALLBACK:
            result = _try_openai(prompt)
            if result:
                model_used = FALLBACK_OPENAI
                _log_audit(caller, process_type, FALLBACK_OPENAI, "openai",
                           int((time.time()-t0)*1000), "ok", fallback_used=True)
                return result
            result = _try_anthropic(prompt)
            if result:
                model_used = FALLBACK_ANTHROPIC
                _log_audit(caller, process_type, FALLBACK_ANTHROPIC, "anthropic",
                           int((time.time()-t0)*1000), "ok", fallback_used=True)
                return result
        _log_audit(caller, process_type, "", "none", int((time.time()-t0)*1000), "all_failed")
        return ""

    try:
        # Tier 1: local model (fast)
        if fast:
            result = _try_ollama(prompt, min(timeout, 30), model=OLLAMA_MODEL_FAST)
            if result:
                model_used = OLLAMA_MODEL_FAST
                _log_audit(caller, process_type, OLLAMA_MODEL_FAST, "ollama",
                           int((time.time()-t0)*1000), "ok")
                return result
        # Tier 2: local model (full) with retry
        result = _try_ollama(prompt, timeout, model=OLLAMA_MODEL, retries=1)
        if result:
            model_used = OLLAMA_MODEL
            _log_audit(caller, process_type, OLLAMA_MODEL, "ollama",
                       int((time.time()-t0)*1000), "ok")
            return result
    finally:
        _gate.release()

    # Local failed — log it
    _log_audit(caller, process_type, OLLAMA_MODEL, "ollama",
               int((time.time()-t0)*1000), "local_failed")

    # Paid cloud fallbacks (only if ALLOW_PAID_FALLBACK=true)
    if fallback and ALLOW_PAID_FALLBACK:
        print(f"  [local-llm] Using OpenAI fallback ({FALLBACK_OPENAI})")
        result = _try_openai(prompt)
        if result:
            model_used = FALLBACK_OPENAI
            _log_audit(caller, process_type, FALLBACK_OPENAI, "openai",
                       int((time.time()-t0)*1000), "ok", fallback_used=True)
            return result

    if fallback and ALLOW_PAID_FALLBACK:
        print(f"  [local-llm] Using Anthropic fallback ({FALLBACK_ANTHROPIC})")
        result = _try_anthropic(prompt)
        if result:
            model_used = FALLBACK_ANTHROPIC
            _log_audit(caller, process_type, FALLBACK_ANTHROPIC, "anthropic",
                       int((time.time()-t0)*1000), "ok", fallback_used=True)
            return result

    _log_audit(caller, process_type, "", "none", int((time.time()-t0)*1000), "all_failed")
    print("  [local-llm] All LLM attempts failed — returning empty")
    return ""


# ── Cache-aware generate wrapper ──

def cached_generate(prompt: str, cache_key: str, *,
                    tier: str = "default", ttl_hours: float | None = None,
                    **kwargs) -> tuple[str, bool]:
    """Cache-aware version of generate(). Checks llm_cache before trying models.
    Returns (text, was_cached) tuple.
    """
    model = _DEEPSEEK_FLASH_MODEL
    try:
        from lib.llm_cache import llm_cache_get, llm_cache_put
        cached = llm_cache_get(cache_key, model)
        if cached is not None:
            return cached, True
    except Exception:
        pass

    text = generate(prompt, **kwargs)

    if text:
        try:
            from lib.llm_cache import llm_cache_put
            llm_cache_put(cache_key, model, text,
                         ttl_hours=ttl_hours, prompt=prompt, tier=tier)
        except Exception:
            pass

    return text, False


if __name__ == "__main__":
    # Quick test
    test = generate(
        "Say 'local LLM working' and nothing else.",
        timeout=30
    )
    print(f"Test result: {test}")


# ── V6 TICKET OVERSIGHT (2026-07-22): LOCAL-ONLY generation — cloud fallback
#    is STRUCTURALLY IMPOSSIBLE here. This function talks to the local Ollama
#    socket and nothing else: no OpenAI, no Anthropic, no OAuth proxy, no retry
#    into cloud. On failure the caller gets ok=False and must report
#    UNAVAILABLE — never a substituted cloud answer still labelled LOCAL.
def generate_local_only(prompt: str, *, system: str = "",
                        timeout_s: int | None = None) -> dict:
    import json as _json
    import urllib.request as _rq
    models = [m.strip() for m in os.getenv(
        "LOCAL_TICKET_CRITIC_MODELS", "gemma3:12b,gemma3:4b").split(",") if m.strip()]
    timeout_s = timeout_s or int(os.getenv("LOCAL_TICKET_CRITIC_TIMEOUT_S", "90"))
    last_err = "no local models configured"
    for model in models:
        body = _json.dumps({"model": model, "prompt": prompt, "system": system,
                            "stream": False,
                            "options": {"temperature": 0.1, "num_predict": 900}}).encode()
        req = _rq.Request(OLLAMA_BASE + "/api/generate", data=body,
                          headers={"Content-Type": "application/json"})
        try:
            with _rq.urlopen(req, timeout=timeout_s) as r:
                out = _json.loads(r.read())
            text = out.get("response") or ""
            if text.strip():
                return {"ok": True, "model": model,
                        "provider_family": "LOCAL_OLLAMA", "text": text}
            last_err = f"{model}: empty response"
        except Exception as e:
            last_err = f"{model}: {type(e).__name__}: {str(e)[:120]}"
    return {"ok": False, "error": last_err, "provider_family": "LOCAL_OLLAMA"}
