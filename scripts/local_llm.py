"""
local_llm.py — Local Ollama LLM with cloud fallback
Use for non-time-sensitive narrative generation to save API costs.

Usage:
    from local_llm import generate

    text = generate(prompt, timeout=120)
    # Returns text from Ollama if available, falls back to Claude Sonnet
"""
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
FALLBACK_OPENAI = "gpt-5.4-mini"
FALLBACK_ANTHROPIC = "claude-sonnet-4-6"
DEFAULT_TIMEOUT = 120
model_used = None  # tracks which model last responded  # seconds before fallback


def warmup_ollama(model: str = None) -> bool:
    """Ping Ollama to ensure model is loaded before batch analysis."""
    model = model or OLLAMA_MODEL
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": "ready"}],
        "think": False,
        "options": {"num_predict": 5}
    }).encode()
    try:
        req = urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            print(f"  [local-llm] Ollama warmup OK — model {model} loaded")
            return True
    except Exception as e:
        print(f"  [local-llm] Ollama warmup failed: {e}")
        return False


def _try_ollama(prompt: str, timeout: int, model: str = OLLAMA_MODEL,
                retries: int = 1) -> str | None:
    """Try Ollama with retry logic. Returns text or None on failure/timeout."""
    import time as _time
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "think": False,
        "options": {"temperature": 0.3, "num_predict": 500}
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
                _time.sleep(5)
                continue
            return None
        except Exception as e:
            print(f"  [local-llm] Ollama error: {e} "
                  f"(attempt {attempt+1}/{retries+1})")
            if attempt < retries:
                _time.sleep(3)
                continue
            return None
    return None


def _try_openai(prompt: str) -> str | None:
    """Fallback to OpenAI gpt-5.4-mini."""
    try:
        import os
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
        import urllib.request, json as _j
        payload = _j.dumps({
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
            data = _j.loads(resp.read())
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
            # Try reading from .env
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
            model=f"claude-{FALLBACK_MODEL}",
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
    """4-tier chain: local model -> OpenAI -> Anthropic"""
    global model_used
    model_used = None
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

    # Tier 3: OpenAI fallback
    if fallback:
        print(f"  [local-llm] Using OpenAI fallback ({FALLBACK_OPENAI})")
        result = _try_openai(prompt)
        if result:
            return result

    # Tier 4: Anthropic final fallback
    if fallback:
        print(f"  [local-llm] Using Anthropic fallback ({FALLBACK_ANTHROPIC})")
        result = _try_anthropic(prompt)
        if result:
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
