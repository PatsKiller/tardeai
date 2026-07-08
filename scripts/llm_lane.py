"""llm_lane.py — unified FREE LLM lanes: Grok OAuth (xAI proxy :8645), ChatGPT OAuth (codex proxy :8646),
or local gemma. No metered APIs, no API keys.

All cloud lanes are free OAuth via local proxies (Grok = hermes xAI proxy; ChatGPT = chatgpt_oauth_proxy.py
driving the authed hermes openai-codex CLI). Local gemma via ollama. generate() returns the raw text; the
caller parses. `available()` uses lib.oauth_lane_status (canonical). Pass process_id to enable consumption
tracking + Automated/Manual gating (lib.llm_consumption).
"""
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_GROK_URL = os.environ.get("HERMES_XAI_PROXY_URL", "http://127.0.0.1:8645/v1/chat/completions")
_CHATGPT_URL = os.environ.get("CHATGPT_PROXY_URL", "http://127.0.0.1:8646").rstrip("/")


def available(lane):
    lane = (lane or "").lower()
    if lane == "local":
        try:
            import requests
            return bool(requests.get("http://127.0.0.1:11434/api/tags", timeout=4).ok)
        except Exception:
            return False
    if lane in ("grok", "chatgpt"):
        try:
            from lib.oauth_lane_status import lane_available
            return lane_available(lane)
        except Exception:
            try:
                import requests
                if lane == "grok":
                    h = requests.get(_GROK_URL.replace("/v1/chat/completions", "/health"), timeout=5).json()
                    return bool(h.get("authenticated")) and not h.get("token_expired")
                h = requests.get(_CHATGPT_URL + "/health", timeout=5).json()
                return bool(h.get("authenticated")) and not h.get("token_expired")
            except Exception:
                return False
    return True


def generate(
    prompt,
    lane="grok",
    timeout=90,
    model=None,
    *,
    process_id=None,
    task_summary=None,
    manual_trigger=False,
    metadata=None,
    _skip_consumption=False,
):
    """Generate text. When process_id is set, routes through consumption gate (Automated/Manual)."""
    if process_id and not _skip_consumption and lane in ("grok", "chatgpt"):
        from lib.llm_consumption import gate_and_generate
        return gate_and_generate(
            prompt, lane=lane, process_id=process_id, task_summary=task_summary,
            manual_trigger=manual_trigger, timeout=timeout, model=model, metadata=metadata,
        )
    lane = (lane or "grok").lower()
    if lane == "grok":
        import requests
        r = requests.post(_GROK_URL, json={"model": model or "grok-3-mini",
                                           "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
                          timeout=timeout)
        r.raise_for_status()
        body = r.json()
        if process_id and not _skip_consumption:
            try:
                from lib.llm_consumption import log_call
                text = body["choices"][0]["message"]["content"]
                usage = body.get("usage") or {}
                log_call(lane="grok", process_id=process_id, task_summary=task_summary or prompt[:160],
                         trigger_mode="automated", success=True, model_name=model or "grok-3-mini",
                         prompt=prompt, response=text,
                         tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))
            except Exception:
                pass
        return body["choices"][0]["message"]["content"]
    if lane == "chatgpt":
        import requests
        r = requests.post(_CHATGPT_URL + "/v1/chat/completions",
                          json={"model": model or "gpt-5.4", "messages": [{"role": "user", "content": prompt}]},
                          timeout=timeout)
        if r.status_code == 401:
            raise RuntimeError("AUTH_EXPIRED: " + (r.json().get("error", {}) or {}).get("message", "ChatGPT session ended"))
        r.raise_for_status()
        body = r.json()
        if process_id and not _skip_consumption:
            try:
                from lib.llm_consumption import log_call
                text = body["choices"][0]["message"]["content"]
                usage = body.get("usage") or {}
                log_call(lane="chatgpt", process_id=process_id, task_summary=task_summary or prompt[:160],
                         trigger_mode="automated", success=True, model_name=model or "gpt-5.4",
                         prompt=prompt, response=text,
                         tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))
            except Exception:
                pass
        return body["choices"][0]["message"]["content"]
    import local_llm
    return local_llm.generate(prompt, timeout=timeout)