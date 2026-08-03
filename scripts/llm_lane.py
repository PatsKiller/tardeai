"""llm_lane.py — unified LLM lanes: DeepSeek Flash (PRIMARY), Grok OAuth, ChatGPT OAuth,
and local gemma (fallback).

DeepSeek Flash is the PRIMARY lane for all agent analysis, classification, and research.
Grok/ChatGPT OAuth and local Ollama are fallback lanes. DeepSeek v4 is available for CIO-level
reasoning via the deepseek-v4 lane.

Key is fetched from Bitwarden SM (`deepseek_tradeai`) and loaded via tmpfs env.

generate() returns the raw text; the caller parses. `available()` checks lane liveness.
Pass process_id to enable consumption tracking + Automated/Manual gating (lib.llm_consumption).
"""
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_DEEPSEEK_API_KEY = os.environ.get("deepseek_tradeai", "").strip()
_DEEPSEEK_FLASH_URL = "https://api.deepseek.com/v1/chat/completions"
# deepseek-chat = non-reasoning bulk model (returns content JSON reliably).
# deepseek-v4-flash is a REASONER: it burns max_tokens on reasoning_content and often
# leaves content empty (finish_reason=length) — that made ticket critics show UNAVAILABLE.
_DEEPSEEK_FLASH_MODEL = os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-chat").strip() or "deepseek-chat"
# CIO / heavy: reasoner-class pro (or env override)
_DEEPSEEK_V4_MODEL = os.environ.get("DEEPSEEK_V4_MODEL", "deepseek-reasoner").strip() or "deepseek-reasoner"

# ── Lane label helper (single source of truth for user-facing labels) ──────────
LANE_LABELS: dict[str, str] = {
    "deepseek-flash": "DeepSeek Flash",
    "deepseek-v4": "DeepSeek v4",
    "deepseek": "DeepSeek",
    "grok": "Grok OAuth",
    "chatgpt": "ChatGPT OAuth",
    "local": "Gemma (local)",
    "claude": "Claude (via DeepSeek v4)",
    "openai": "OpenAI (via DeepSeek Flash)",
}

def lane_label(lane_id: str) -> str:
    """Return a human-readable label for a lane identifier."""
    return LANE_LABELS.get((lane_id or "").lower().strip(), lane_id or "Unknown")
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
    if lane in ("deepseek-flash", "deepseek-v4", "deepseek"):
        if not _DEEPSEEK_API_KEY:
            return False
        try:
            import requests
            # Lightweight chat-completion ping (DeepSeek /v1/models often 404s/401s)
            r = requests.post(_DEEPSEEK_FLASH_URL,
                            json={"model": _DEEPSEEK_FLASH_MODEL,
                                  "messages": [{"role": "user", "content": "ping"}],
                                  "max_tokens": 1, "temperature": 0},
                            headers={"Authorization": f"Bearer {_DEEPSEEK_API_KEY}",
                                     "Content-Type": "application/json"},
                            timeout=10)
            return r.ok
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


def _deepseek_message_text(body: dict) -> str:
    """Extract assistant text from DeepSeek chat completions.

    Some v4-flash responses put the usable answer in ``reasoning_content`` with
    empty ``content`` (or vice versa). Prefer content, then reasoning, then "".
    """
    try:
        msg = ((body or {}).get("choices") or [{}])[0].get("message") or {}
    except Exception:
        return ""
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content
    reasoning = msg.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    # content may be a list of parts
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("text"):
                parts.append(str(part["text"]))
        joined = "\n".join(parts).strip()
        if joined:
            return joined
    return (content or reasoning or "") if isinstance(content or reasoning, str) else ""


def generate(
    prompt,
    lane="deepseek-flash",
    timeout=90,
    model=None,
    *,
    process_id=None,
    task_summary=None,
    manual_trigger=False,
    metadata=None,
    _skip_consumption=False,
):
    """Generate text. PRIMARY: DeepSeek Flash. Fallback chain: gemma3:4b (local) -> grok OAuth.
    When process_id is set, routes through consumption gate for cloud lanes."""
    lane = (lane or "deepseek-flash").lower()

    # ── DeepSeek Flash (PRIMARY) ──
    if lane in ("deepseek-flash", "deepseek"):
        if not _DEEPSEEK_API_KEY:
            return generate(prompt, lane="local", timeout=timeout, model=model,
                          process_id=process_id, task_summary=task_summary,
                          manual_trigger=manual_trigger, metadata=metadata)
        import requests
        try:
            use_model = model or _DEEPSEEK_FLASH_MODEL
            payload = {
                "model": use_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2 if (process_id or "") == "ticket_review" else 0.3,
                "max_tokens": 2048,
            }
            # Force JSON object when the caller is the ticket critic schema path.
            if (process_id or "") == "ticket_review" and "reasoner" not in use_model:
                payload["response_format"] = {"type": "json_object"}
            r = requests.post(
                _DEEPSEEK_FLASH_URL,
                json=payload,
                headers={"Authorization": f"Bearer {_DEEPSEEK_API_KEY}"},
                timeout=timeout,
            )
            r.raise_for_status()
            body = r.json()
            text = _deepseek_message_text(body)
            if not (text or "").strip():
                raise RuntimeError("DeepSeek Flash returned empty content/reasoning_content")
            if process_id and not _skip_consumption:
                try:
                    from lib.llm_consumption import log_call
                    usage = body.get("usage") or {}
                    log_call(lane="deepseek-flash", process_id=process_id,
                             task_summary=task_summary or prompt[:160],
                             trigger_mode="manual" if manual_trigger else "automated",
                             success=True,
                             model_name=use_model,
                             prompt=prompt, response=text,
                             tokens_in=usage.get("prompt_tokens"),
                             tokens_out=usage.get("completion_tokens"))
                except Exception:
                    pass
            return text
        except Exception as e:
            print(f"  [llm-lane] DeepSeek Flash failed ({e}), falling back to local gemma")
            return generate(prompt, lane="local", timeout=timeout, model=model,
                          process_id=process_id, task_summary=task_summary,
                          manual_trigger=manual_trigger, metadata=metadata)

    # ── DeepSeek v4 (CIO-level reasoning) ──
    if lane == "deepseek-v4":
        if not _DEEPSEEK_API_KEY:
            return generate(prompt, lane="grok", timeout=timeout, model=model,
                          process_id=process_id, task_summary=task_summary,
                          manual_trigger=manual_trigger, metadata=metadata)
        import requests
        try:
            # Ticket critics need schema JSON; reasoner often exhausts tokens on CoT.
            # Give more room (8192) and slightly lower temp. Callers that require
            # strict JSON should still retry on deepseek-chat if parse fails.
            use_model = model or _DEEPSEEK_V4_MODEL
            max_tok = 8192 if (process_id or "") == "ticket_review" else 4096
            payload = {
                "model": use_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.15,
                "max_tokens": max_tok,
            }
            # json_object helps chat models; reasoner may ignore or reject — try only on chat.
            if "reasoner" not in use_model and (process_id or "") == "ticket_review":
                payload["response_format"] = {"type": "json_object"}
            r = requests.post(
                _DEEPSEEK_FLASH_URL,
                json=payload,
                headers={"Authorization": f"Bearer {_DEEPSEEK_API_KEY}"},
                timeout=max(timeout, 180),
            )
            r.raise_for_status()
            body = r.json()
            text = _deepseek_message_text(body)
            if not (text or "").strip():
                raise RuntimeError("DeepSeek v4 returned empty content/reasoning_content")
            if process_id and not _skip_consumption:
                try:
                    from lib.llm_consumption import log_call
                    usage = body.get("usage") or {}
                    log_call(lane="deepseek-v4", process_id=process_id,
                             task_summary=task_summary or prompt[:160],
                             trigger_mode="manual" if manual_trigger else "automated",
                             success=True,
                             model_name=use_model,
                             prompt=prompt, response=text,
                             tokens_in=usage.get("prompt_tokens"),
                             tokens_out=usage.get("completion_tokens"))
                except Exception:
                    pass
            return text
        except Exception as e:
            print(f"  [llm-lane] DeepSeek v4 failed ({e}), falling back to deepseek-chat then grok")
            # Prefer chat (same provider, schema-friendly) before OAuth fallback
            try:
                return generate(
                    prompt,
                    lane="deepseek-flash",
                    model=_DEEPSEEK_FLASH_MODEL,
                    timeout=timeout,
                    process_id=process_id,
                    task_summary=task_summary,
                    manual_trigger=manual_trigger,
                    metadata=metadata,
                )
            except Exception:
                return generate(prompt, lane="grok", timeout=timeout, model=model,
                              process_id=process_id, task_summary=task_summary,
                              manual_trigger=manual_trigger, metadata=metadata)

    # ── Free OAuth lanes (fallback) ──
    if process_id and not _skip_consumption and lane in ("grok", "chatgpt"):
        from lib.llm_consumption import gate_and_generate
        return gate_and_generate(
            prompt, lane=lane, process_id=process_id, task_summary=task_summary,
            manual_trigger=manual_trigger, timeout=timeout, model=model, metadata=metadata,
        )
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

    # ── Local gemma (final fallback) ──
    import local_llm
    return local_llm.generate(prompt, timeout=timeout)


# ── Cache-aware generate wrapper ──

def cached_generate(cache_key, model, prompt, *,
                    lane="deepseek-flash", tier="default",
                    ttl_hours=None, timeout=90, **kwargs):
    """Cache-aware version of generate(). Checks llm_cache before calling API.
    Callers must provide a deterministic cache_key (see lib.llm_cache.build_cache_key).

    Returns (text, was_cached) tuple.
    """
    try:
        from lib.llm_cache import llm_cache_get, llm_cache_put
        cached = llm_cache_get(cache_key, model or _DEEPSEEK_FLASH_MODEL)
        if cached is not None:
            return cached, True
    except Exception:
        pass

    text = generate(prompt, lane=lane, model=model, timeout=timeout, **kwargs)

    if text:
        try:
            from lib.llm_cache import llm_cache_put
            llm_cache_put(cache_key, model or _DEEPSEEK_FLASH_MODEL, text,
                         ttl_hours=ttl_hours, prompt=prompt, tier=tier)
        except Exception:
            pass

    return text, False