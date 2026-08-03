"""Manual Consumption route: free OAuth + DeepSeek FAST smoke only.

POST /api/v2/consumption/run-manual must NOT execute PRO / PRO_THINK / PRO_MAX.
Pro remains on the governed premium path (estimate → typed confirm → server validation).

Never expose secret names or values in browser-facing payloads.
"""
from __future__ import annotations

import threading
import time
from typing import Any

# Free OAuth only on this endpoint (plus DeepSeek FAST for registered smoke process)
OAUTH_LANES = frozenset({"grok", "chatgpt"})

# Generic endpoint Flash aliases → FAST only (no PRO family)
FLASH_LANES = frozenset({
    "deepseek-flash",
    "deepseek-v4-flash",
    "fast",
})

# FAST_THINK only when process allowlist includes it (not on smoke process)
FLASH_THINK_LANES = frozenset({"fast_think"})

# Explicitly forbidden on this endpoint regardless of body flags
FORBIDDEN_PRO_LANES = frozenset({
    "deepseek-v4-pro",
    "deepseek-pro",
    "pro",
    "pro_think",
    "pro_max",
    "PRO",
    "PRO_THINK",
    "PRO_MAX",
})

AMBIGUOUS = frozenset({"deepseek-v4", "deepseek_v4", "v4"})
LEGACY = frozenset({"deepseek-chat", "deepseek-reasoner"})

LANE_TO_POLICY = {
    "deepseek-flash": "FAST",
    "deepseek-v4-flash": "FAST",
    "fast": "FAST",
    "fast_think": "FAST_THINK",
}

POLICY_TO_MODEL = {
    "FAST": "deepseek-v4-flash",
    "FAST_THINK": "deepseek-v4-flash",
}

SMOKE_PROCESS_ID = "deepseek_flash_operator_smoke"

# Capability probe cache (process-local)
_PROBE_LOCK = threading.Lock()
_PROBE_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_PROBE_TTL_SEC = 60.0


def parse_operator_confirmed(raw: Any) -> bool:
    """Strict confirmation parser — never use bare bool() on strings.

    Only explicit True or the exact string \"true\" (case-insensitive, stripped)
    count. \"false\", \"0\", 1, \"yes\", etc. do NOT authorize paid Pro paths.
    """
    if raw is True:
        return True
    if isinstance(raw, str) and raw.strip().lower() == "true":
        return True
    return False


def classify_manual_lane(lane: str, *, operator_confirmed: Any = None) -> dict[str, Any]:
    """Classify run-manual lane. Pro/PRO_MAX always rejected on this endpoint."""
    # operator_confirmed deliberately ignored for Pro — cannot authorize Pro here
    _ = parse_operator_confirmed(operator_confirmed)

    raw = (lane or "grok").strip().lower()
    if not raw:
        return _fail(raw, "LANE_REQUIRED", "lane required")

    if raw in AMBIGUOUS or raw.upper() in ("DEEPSEEK-V4",):
        return _fail(
            raw, "AMBIGUOUS_LEGACY_LANE",
            "Ambiguous DeepSeek id rejected. Use deepseek-flash / FAST only on this endpoint.",
        )
    if raw in LEGACY:
        return _fail(
            raw, "LEGACY_MODEL_REJECTED",
            "Legacy DeepSeek model ids are rejected.",
        )

    # Uppercase logical policies
    up = raw.upper()
    if up in ("PRO", "PRO_THINK", "PRO_MAX") or raw in FORBIDDEN_PRO_LANES or raw.upper() in FORBIDDEN_PRO_LANES:
        return _fail(
            raw, "POLICY_NOT_ALLOWED",
            "PRO/PRO_THINK/PRO_MAX cannot use the generic manual endpoint. "
            "Use the governed premium estimate → typed confirmation flow.",
        )
    if up == "FAST":
        return _ok_deepseek(raw, "FAST")
    if up == "FAST_THINK":
        return _ok_deepseek(raw, "FAST_THINK")

    if raw in OAUTH_LANES:
        return {
            "ok": True, "kind": "oauth", "lane": raw, "policy": None,
            "requested_model_id": None, "error": None, "reason_code": None,
        }

    if raw in FLASH_LANES:
        return _ok_deepseek(raw, "FAST")
    if raw in FLASH_THINK_LANES:
        return _ok_deepseek(raw, "FAST_THINK")

    return _fail(
        raw, "LANE_NOT_ALLOWED",
        "lane must be grok, chatgpt, deepseek-flash, or FAST on this endpoint",
    )


def _ok_deepseek(lane: str, policy: str) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": "deepseek",
        "lane": lane,
        "policy": policy,
        "requested_model_id": POLICY_TO_MODEL[policy],
        "error": None,
        "reason_code": None,
    }


def _fail(lane: str, code: str, msg: str) -> dict[str, Any]:
    return {
        "ok": False, "kind": None, "lane": lane, "policy": None,
        "requested_model_id": None, "error": msg, "reason_code": code,
    }


def process_allows_policy(process_id: str, policy: str | None, lane: str) -> dict[str, Any]:
    """Fail closed: process must be registered; policy/lane must be explicitly allowed."""
    from lib import llm_consumption as lc

    pid = str(process_id or "").strip()
    if not pid:
        return {"ok": False, "reason_code": "PROCESS_NOT_REGISTERED", "error": "process_id required"}
    if not lc.is_process_registered(pid):
        return {
            "ok": False,
            "reason_code": "PROCESS_NOT_REGISTERED",
            "error": "process_id is not registered",
        }
    cfg = lc.get_process_config(pid)
    allowed = {str(x).lower() for x in (cfg.get("allowed_lanes") or [])}
    allowed_pols = {str(x).upper() for x in (cfg.get("deepseek_allowed_policies") or [])}

    if policy:
        pu = policy.upper()
        if allowed_pols and pu not in allowed_pols:
            return {
                "ok": False,
                "reason_code": "POLICY_NOT_ALLOWED",
                "error": "requested policy is not allowed for this process",
            }
        # Also require lane alias present when listed
        lane_l = (lane or "").lower()
        if allowed and lane_l not in allowed and pu.lower() not in allowed:
            # FAST may be listed as policy only
            if pu not in allowed_pols:
                return {
                    "ok": False,
                    "reason_code": "POLICY_NOT_ALLOWED",
                    "error": "requested lane is not allowed for this process",
                }
    else:
        # OAuth
        if (lane or "").lower() not in allowed and allowed:
            return {
                "ok": False,
                "reason_code": "POLICY_NOT_ALLOWED",
                "error": "requested lane is not allowed for this process",
            }
    return {"ok": True, "config": cfg}


def projected_max_cost_usd(*, model_id: str, max_input_tokens: int, max_output_tokens: int) -> float:
    from lib.llm_model_registry import estimate_usd_cost

    est = estimate_usd_cost(
        model_id=model_id,
        prompt_tokens=int(max_input_tokens),
        completion_tokens=int(max_output_tokens),
    )
    val = est.get("estimated_cost_usd")
    if val is None:
        # Fail closed for paid: require pricing snapshot
        raise RuntimeError("COST_CAP_EXCEEDED: pricing unavailable for projected cost")
    # Conservative headroom
    return float(val) * 1.15


def sanitize_provider_error(exc: BaseException | str) -> dict[str, str]:
    """Map exceptions to safe browser reason codes — never raw exception text."""
    raw = str(exc) if not isinstance(exc, str) else exc
    u = raw.upper()
    mapping = [
        ("AUTH_MISSING", "AUTH_MISSING", "Provider authentication is not available"),
        ("AUTH_INVALID", "AUTH_INVALID", "Provider authentication was rejected"),
        ("HTTP_401", "AUTH_INVALID", "Provider authentication was rejected"),
        ("HTTP_403", "AUTH_INVALID", "Provider authentication was rejected"),
        ("HTTP_429", "RATE_LIMITED", "Provider rate limit reached"),
        ("RATE_LIMIT", "RATE_LIMITED", "Provider rate limit reached"),
        ("TIMEOUT", "PROVIDER_TIMEOUT", "Provider request timed out"),
        ("MODEL_NOT", "MODEL_NOT_AVAILABLE", "Requested model is not available"),
        ("MODEL_NOT_AVAILABLE", "MODEL_NOT_AVAILABLE", "Requested model is not available"),
        ("COST_CAP", "COST_CAP_EXCEEDED", "Cost or request cap would be exceeded"),
        ("COST_PERSISTENCE", "COST_CAP_EXCEEDED", "Cost accounting unavailable; paid call blocked"),
        ("PROCESS_NOT_REGISTERED", "PROCESS_NOT_REGISTERED", "process_id is not registered"),
        ("POLICY_NOT_ALLOWED", "POLICY_NOT_ALLOWED", "Policy or lane not allowed for process"),
        ("HTTP_5", "PROVIDER_UNAVAILABLE", "Provider temporarily unavailable"),
        ("NETWORK", "PROVIDER_UNAVAILABLE", "Provider temporarily unavailable"),
        ("PROVIDER", "PROVIDER_UNAVAILABLE", "Provider request failed"),
    ]
    for needle, code, msg in mapping:
        if needle in u:
            return {"reason_code": code, "error": msg}
    return {"reason_code": "PROVIDER_UNAVAILABLE", "error": "Provider request failed"}


def _cached_list_models() -> dict[str, Any] | None:
    """Return cached list_models payload or None if unconfigured / probe failed."""
    now = time.time()
    with _PROBE_LOCK:
        if _PROBE_CACHE["data"] is not None and (now - float(_PROBE_CACHE["at"])) < _PROBE_TTL_SEC:
            return _PROBE_CACHE["data"]
    try:
        from lib.deepseek_client import list_models
        info = list_models(timeout=8)
        # Strip env name before caching browser-facing derivatives
        safe = {
            "ok": bool(info.get("ok")),
            "has_v4_flash": bool(info.get("has_v4_flash")),
            "has_v4_pro": bool(info.get("has_v4_pro")),
            "configured": True,
            "reachable": True,
        }
        with _PROBE_LOCK:
            _PROBE_CACHE["at"] = now
            _PROBE_CACHE["data"] = safe
        return safe
    except Exception as e:
        code = getattr(e, "code", "") or ""
        msg = str(e).upper()
        configured = code not in ("AUTH_MISSING",) and "AUTH_MISSING" not in msg
        # configured-but-unreachable: key may exist but probe failed
        try:
            from lib.llm_model_registry import get_deepseek_api_key
            key, _n, _leg = get_deepseek_api_key()
            configured = bool(key)
        except Exception:
            configured = False
        safe = {
            "ok": False,
            "has_v4_flash": False,
            "has_v4_pro": False,
            "configured": configured,
            "reachable": False,
            "probe_failed": True,
        }
        with _PROBE_LOCK:
            _PROBE_CACHE["at"] = now
            _PROBE_CACHE["data"] = safe
        return safe


def clear_capability_probe_cache() -> None:
    with _PROBE_LOCK:
        _PROBE_CACHE["at"] = 0.0
        _PROBE_CACHE["data"] = None


def deepseek_readiness_rows() -> list[dict[str, Any]]:
    """Independent Flash and Pro readiness. No secret names/values."""
    info = _cached_list_models() or {
        "configured": False, "reachable": False,
        "has_v4_flash": False, "has_v4_pro": False,
    }
    configured = bool(info.get("configured"))
    reachable = bool(info.get("reachable")) and configured

    def row(lane: str, label: str, model_ok: bool) -> dict[str, Any]:
        model_available = bool(model_ok and reachable)
        ready = bool(configured and reachable and model_available)
        if not configured:
            hint, reason = "Provider credentials are not configured for this host process.", "PROVIDER_AUTH_NOT_CONFIGURED"
        elif not reachable:
            hint, reason = "Provider is configured but not reachable.", "PROVIDER_UNAVAILABLE"
        elif not model_available:
            hint, reason = "Exact model is not available from the provider.", "MODEL_NOT_AVAILABLE"
        else:
            hint, reason = None, None
        return {
            "lane": lane,
            "label": label,
            "kind": "metered_api",
            "billing": "metered",
            "configured": configured,
            "reachable": reachable,
            "model_available": model_available,
            "ready": ready,
            "status": "ready" if ready else "offline",
            "authenticated": configured,  # boolean only
            "hint": hint,
            "reason_code": reason,
            "token_expired": False,
        }

    return [
        row("deepseek-flash", "DeepSeek V4 Flash", bool(info.get("has_v4_flash"))),
        row("deepseek-v4-pro", "DeepSeek V4 Pro", bool(info.get("has_v4_pro"))),
    ]
