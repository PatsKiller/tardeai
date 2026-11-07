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
        # Pass-through only (2026-11-07): a 200 from /health has never meant the lane can serve. The
        # proxy states ``serving`` and what the upstream did last (rate_limited / auth_expired / ok),
        # and the keepalive dry run reads them to tell a quota wait from a dead login without spending
        # a generate. Grok's proxy omits both; the values are then None and nothing changes.
        "serving": body.get("serving"),
        "last_upstream": body.get("last_upstream"),
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


# ── Cooldown after a rate limit / timeout (LQ-20261107-236) ─────────────────────────────────────────
# A proxy that answers 429 or stops answering keeps being called by every scheduled caller, and each call
# is a failed row on the consumption page. After such a failure the lane is held out of ``lane_available``
# for a short, growing interval; the next caller then skips it (generate_cloud moves to the next lane)
# instead of adding another failure. A success clears it. This never changes a spend cap.
COOLDOWN_BASE_S = {"rate_limited": 120.0, "unreachable": 60.0}
COOLDOWN_MAX_S = 900.0
_COOLDOWN_FILE = (Path(__file__).resolve().parent.parent.parent / "data" / "runtime" / "oauth_lane_cooldown.json")
_RATE_MARKERS = ("429", "too many requests", "rate limit", "rate_limit")
_UNREACHABLE_MARKERS = ("read timed out", "timed out", "max retries exceeded", "connection refused",
                        "remotedisconnected", "remote end closed", "connection aborted", "connection reset")


def classify_failure(error: str | None) -> str | None:
    """'rate_limited' / 'unreachable' for the errors worth backing off from; None for everything else."""
    text = (error or "").lower()
    if any(m in text for m in _RATE_MARKERS):
        return "rate_limited"
    if any(m in text for m in _UNREACHABLE_MARKERS):
        return "unreachable"
    return None


def _read_cooldowns(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or _COOLDOWN_FILE).read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - an unreadable file means no cooldown, never a blocked lane
        return {}


def _write_cooldowns(data: dict, path: Path | None = None) -> None:
    target = path or _COOLDOWN_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, target)
    except Exception:  # noqa: BLE001 - best effort; losing a cooldown only restores the old behaviour
        pass


def note_failure(lane: str, error: str | None, *, now: float | None = None, path: Path | None = None) -> dict | None:
    """Start or extend the cooldown for a lane after a rate-limit/timeout failure. Returns the entry or None."""
    lane = (lane or "").strip().lower()
    kind = classify_failure(error)
    if lane not in ("grok", "chatgpt") or kind is None:
        return None
    now = time.time() if now is None else now
    data = _read_cooldowns(path)
    prev = data.get(lane) or {}
    prev_until = prev.get("until")
    streak = int(prev.get("streak", 1)) + 1 if isinstance(prev_until, (int, float)) and prev_until > now - COOLDOWN_MAX_S else 1
    wait = min(COOLDOWN_MAX_S, COOLDOWN_BASE_S[kind] * (2 ** min(streak - 1, 3)))
    entry = {"kind": kind, "streak": streak, "until": now + wait, "set_at": now, "error": (error or "")[:120]}
    data[lane] = entry
    _write_cooldowns(data, path)
    _CACHE.pop(lane, None)
    return entry


def note_success(lane: str, *, path: Path | None = None) -> None:
    lane = (lane or "").strip().lower()
    data = _read_cooldowns(path)
    if lane in data:
        data.pop(lane, None)
        _write_cooldowns(data, path)


def cooldown_remaining(lane: str, *, now: float | None = None, path: Path | None = None) -> float:
    """Seconds left on the lane's cooldown, 0.0 when it is not cooling down."""
    now = time.time() if now is None else now
    entry = _read_cooldowns(path).get((lane or "").strip().lower()) or {}
    until = entry.get("until")
    if not isinstance(until, (int, float)):
        return 0.0  # no cooldown recorded (explicitly: not "unknown availability")
    return max(0.0, float(until) - now)


def lane_available(lane: str) -> bool:
    """True when the free OAuth proxy is authenticated, token is not expired and it is not cooling down."""
    if cooldown_remaining(lane) > 0:
        return False
    return bool(lane_status(lane).get("ready"))


def lanes_available() -> dict[str, bool]:
    return {ln: lane_available(ln) for ln in ("grok", "chatgpt")}


def all_lanes(*, include_local: bool = True, use_cache: bool = True) -> list[dict]:
    """Shape compatible with GET /api/v2/llm/oauth-lanes."""
    out = [lane_status("grok", use_cache=use_cache), lane_status("chatgpt", use_cache=use_cache)]
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