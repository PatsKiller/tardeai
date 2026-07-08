"""Canonical FREE OAuth lane health — single source of truth for Grok (:8645) and ChatGPT (:8646).

All availability checks across Trade AI / Command Center should use this module (or llm_lane.available,
which delegates here). Never use XAI_API_KEY / metered API paths for lane availability.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = float(os.environ.get("OAUTH_LANE_CACHE_SEC", "20"))


def _health_url(lane: str) -> str:
    if lane == "grok":
        base = os.environ.get("HERMES_XAI_PROXY_URL", "http://127.0.0.1:8645/v1/chat/completions")
        return base.replace("/v1/chat/completions", "/health")
    if lane == "chatgpt":
        return os.environ.get("CHATGPT_PROXY_URL", "http://127.0.0.1:8646").rstrip("/") + "/health"
    raise ValueError(f"unknown oauth lane: {lane}")


def _probe_health(lane: str, timeout: float = 5.0) -> dict:
    import requests
    url = _health_url(lane)
    try:
        r = requests.get(url, timeout=timeout)
        body = r.json() if r.ok else {}
    except Exception as e:
        return {
            "lane": lane,
            "reachable": False,
            "authenticated": False,
            "token_expired": None,
            "ready": False,
            "status": "offline",
            "error": str(e)[:120],
            "hint": "systemctl --user restart grok-oauth-proxy.service" if lane == "grok"
                    else "systemctl --user restart chatgpt-oauth-proxy.service",
            "kind": "oauth_proxy",
            "port": 8645 if lane == "grok" else 8646,
            "label": "Grok (xAI OAuth)" if lane == "grok" else "ChatGPT (openai-codex OAuth)",
            "billing": "free_oauth",
        }
    authed = bool(body.get("authenticated"))
    expired = bool(body.get("token_expired"))
    ready = authed and not expired
    if not ready:
        status = "offline" if not authed and not body else (
            "session expired" if expired else "not authenticated")
        hint = body.get("note") or (
            "hermes auth add xai-oauth --type oauth" if lane == "grok"
            else "hermes auth add openai-codex --type oauth")
    else:
        status = "ready"
        hint = None
    return {
        "lane": lane,
        "reachable": True,
        "authenticated": authed,
        "token_expired": expired,
        "ready": ready,
        "status": status,
        "hint": hint,
        "upstream": body.get("upstream"),
        "kind": "oauth_proxy",
        "port": 8645 if lane == "grok" else 8646,
        "label": "Grok (xAI OAuth)" if lane == "grok" else "ChatGPT (openai-codex OAuth)",
        "billing": "free_oauth",
        "proxy": body.get("_proxy") or body.get("status"),
    }


def lane_status(lane: str, *, use_cache: bool = True) -> dict:
    lane = (lane or "").strip().lower()
    if lane not in ("grok", "chatgpt"):
        return {"lane": lane, "ready": False, "status": "unknown", "billing": "free_oauth"}
    now = time.time()
    if use_cache and lane in _CACHE:
        ts, snap = _CACHE[lane]
        if now - ts < _CACHE_TTL:
            return dict(snap)
    snap = _probe_health(lane)
    try:
        ks = json.loads((Path(__file__).resolve().parent.parent.parent
                         / "data" / "runtime" / "oauth_lane_status.json").read_text())
        k = ks.get(lane) or {}
        snap["last_ok"] = k.get("last_ok")
        snap["last_check"] = k.get("last_check")
        snap["consec_fail"] = k.get("consec_fail")
    except Exception:
        pass
    _CACHE[lane] = (now, snap)
    return snap


def lane_available(lane: str) -> bool:
    """True when the free OAuth proxy is authenticated and token is not expired."""
    return bool(lane_status(lane).get("ready"))


def lanes_available() -> dict[str, bool]:
    return {ln: lane_available(ln) for ln in ("grok", "chatgpt")}


def all_lanes(*, include_local: bool = True) -> list[dict]:
    """Shape compatible with GET /api/v2/llm/oauth-lanes."""
    out = [lane_status("grok"), lane_status("chatgpt")]
    if include_local:
        import requests
        try:
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
            models = [m.get("name") for m in (r.json().get("models") or [])][:8] if r.ok else []
            out.append({
                "lane": "local", "label": "Local gemma (ollama)", "kind": "local", "port": 11434,
                "reachable": r.ok, "authenticated": r.ok, "ready": r.ok,
                "status": "ready" if r.ok else "offline", "models": models, "billing": "local",
            })
        except Exception:
            out.append({"lane": "local", "label": "Local gemma (ollama)", "kind": "local",
                          "ready": False, "status": "offline", "billing": "local"})
    return out