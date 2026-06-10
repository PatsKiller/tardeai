"""llm_lane.py — unified FREE LLM lane: Grok OAuth (xAI proxy) or local gemma. No metered APIs.

Both lanes are free (OAuth Grok via the local proxy; local gemma via ollama). generate() returns the raw
text; the caller parses. `available()` lets a runner fall back local→grok or grok→local.
"""
import os


def available(lane):
    lane = (lane or "").lower()
    if lane == "grok":
        try:
            import requests
            url = os.environ.get("HERMES_XAI_PROXY_URL", "http://127.0.0.1:8645/v1/chat/completions").replace("/v1/chat/completions", "/health")
            return bool(requests.get(url, timeout=4).json().get("authenticated"))
        except Exception:
            return False
    return True  # local gemma assumed reachable (the runner handles failures)


def generate(prompt, lane="grok", timeout=90, model=None):
    lane = (lane or "grok").lower()
    if lane == "grok":
        import requests
        url = os.environ.get("HERMES_XAI_PROXY_URL", "http://127.0.0.1:8645/v1/chat/completions")
        r = requests.post(url, json={"model": model or "grok-3-mini",
                                     "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
                          timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    import local_llm
    return local_llm.generate(prompt, timeout=timeout)
