"""llm_lane.py — unified FREE LLM lanes: Grok OAuth (xAI proxy :8645), ChatGPT OAuth (codex proxy :8646),
or local gemma. No metered APIs, no API keys.

All cloud lanes are free OAuth via local proxies (Grok = hermes xAI proxy; ChatGPT = chatgpt_oauth_proxy.py
driving the authed hermes openai-codex CLI). Local gemma via ollama. generate() returns the raw text; the
caller parses. `available()` lets a runner fall back across lanes.
"""
import os

_GROK_URL = os.environ.get("HERMES_XAI_PROXY_URL", "http://127.0.0.1:8645/v1/chat/completions")
_CHATGPT_URL = os.environ.get("CHATGPT_PROXY_URL", "http://127.0.0.1:8646").rstrip("/")


def available(lane):
    lane = (lane or "").lower()
    if lane == "grok":
        try:
            import requests
            return bool(requests.get(_GROK_URL.replace("/v1/chat/completions", "/health"), timeout=4).json().get("authenticated"))
        except Exception:
            return False
    if lane == "chatgpt":
        try:
            import requests
            h = requests.get(_CHATGPT_URL + "/health", timeout=4).json()
            # authenticated AND not a known-expired token (a call still confirms true validity)
            return bool(h.get("authenticated")) and not h.get("token_expired")
        except Exception:
            return False
    return True  # local gemma assumed reachable (the runner handles failures)


def generate(prompt, lane="grok", timeout=90, model=None):
    lane = (lane or "grok").lower()
    if lane == "grok":
        import requests
        r = requests.post(_GROK_URL, json={"model": model or "grok-3-mini",
                                           "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
                          timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if lane == "chatgpt":
        import requests
        r = requests.post(_CHATGPT_URL + "/v1/chat/completions",
                          json={"model": model or "gpt-5.4", "messages": [{"role": "user", "content": prompt}]},
                          timeout=timeout)
        if r.status_code == 401:
            raise RuntimeError("AUTH_EXPIRED: " + (r.json().get("error", {}) or {}).get("message", "ChatGPT session ended"))
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    import local_llm
    return local_llm.generate(prompt, timeout=timeout)
