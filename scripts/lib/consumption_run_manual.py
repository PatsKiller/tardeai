"""Manual Consumption route lane policy for OAuth + DeepSeek V4.

Used by POST /api/v2/consumption/run-manual. Keeps validation pure for unit tests.
Never exposes secret names or values in browser-facing reason codes.
"""
from __future__ import annotations

from typing import Any

# Free OAuth only
OAUTH_LANES = frozenset({"grok", "chatgpt"})

# Map to FAST / FAST_THINK without cost confirmation
FLASH_LANES = frozenset({
    "deepseek-flash",
    "deepseek-v4-flash",
    "fast",
    "fast_think",
})

# Require operator_confirmed (estimate → typed confirm path)
PRO_LANES = frozenset({
    "deepseek-v4-pro",
    "deepseek-pro",
    "pro",
    "pro_think",
})

PRO_MAX_LANES = frozenset({"pro_max"})

AMBIGUOUS = frozenset({"deepseek-v4", "deepseek_v4", "v4"})
LEGACY = frozenset({"deepseek-chat", "deepseek-reasoner"})

LANE_TO_POLICY = {
    "deepseek-flash": "FAST",
    "deepseek-v4-flash": "FAST",
    "fast": "FAST",
    "fast_think": "FAST_THINK",
    "deepseek-v4-pro": "PRO",
    "deepseek-pro": "PRO",
    "pro": "PRO",
    "pro_think": "PRO_THINK",
    "pro_max": "PRO_MAX",
}

POLICY_TO_MODEL = {
    "FAST": "deepseek-v4-flash",
    "FAST_THINK": "deepseek-v4-flash",
    "PRO": "deepseek-v4-pro",
    "PRO_THINK": "deepseek-v4-pro",
    "PRO_MAX": "deepseek-v4-pro",
}


def classify_manual_lane(lane: str, *, operator_confirmed: bool = False) -> dict[str, Any]:
    """Classify a run-manual lane argument.

    Returns dict with keys:
      ok: bool
      kind: 'oauth' | 'deepseek' | None
      lane: normalized lane
      policy: logical policy or None
      requested_model_id: exact model or None
      error: machine-readable message if not ok
      reason_code: short code for UI (no secrets)
    """
    raw = (lane or "grok").strip().lower()
    if not raw:
        return {
            "ok": False, "kind": None, "lane": raw, "policy": None,
            "requested_model_id": None,
            "error": "lane required",
            "reason_code": "LANE_REQUIRED",
        }

    if raw in AMBIGUOUS:
        return {
            "ok": False, "kind": None, "lane": raw, "policy": None,
            "requested_model_id": None,
            "error": (
                "AMBIGUOUS_LEGACY_LANE: 'deepseek-v4' is not exact. "
                "Use FAST/FAST_THINK/PRO/PRO_THINK/PRO_MAX or deepseek-v4-flash / deepseek-v4-pro."
            ),
            "reason_code": "AMBIGUOUS_LEGACY_LANE",
        }

    if raw in LEGACY:
        return {
            "ok": False, "kind": None, "lane": raw, "policy": None,
            "requested_model_id": None,
            "error": (
                f"LEGACY_MODEL_REJECTED: {raw!r} remaps on provider to Flash. "
                "Use deepseek-v4-flash / deepseek-v4-pro only."
            ),
            "reason_code": "LEGACY_MODEL_REJECTED",
        }

    if raw in OAUTH_LANES:
        return {
            "ok": True, "kind": "oauth", "lane": raw, "policy": None,
            "requested_model_id": None, "error": None, "reason_code": None,
        }

    if raw in FLASH_LANES:
        pol = LANE_TO_POLICY[raw]
        return {
            "ok": True, "kind": "deepseek", "lane": raw, "policy": pol,
            "requested_model_id": POLICY_TO_MODEL[pol],
            "error": None, "reason_code": None,
        }

    if raw in PRO_MAX_LANES:
        if not operator_confirmed:
            return {
                "ok": False, "kind": "deepseek", "lane": raw, "policy": "PRO_MAX",
                "requested_model_id": "deepseek-v4-pro",
                "error": "PRO_MAX requires explicit operator cost confirmation (operator_confirmed=true)",
                "reason_code": "PRO_MAX_CONFIRMATION_REQUIRED",
            }
        return {
            "ok": True, "kind": "deepseek", "lane": raw, "policy": "PRO_MAX",
            "requested_model_id": "deepseek-v4-pro",
            "error": None, "reason_code": None,
        }

    if raw in PRO_LANES:
        pol = LANE_TO_POLICY[raw]
        if not operator_confirmed:
            return {
                "ok": False, "kind": "deepseek", "lane": raw, "policy": pol,
                "requested_model_id": POLICY_TO_MODEL[pol],
                "error": (
                    "PRO_CONFIRMATION_REQUIRED: paid Pro requires estimate → typed confirmation. "
                    "Pass operator_confirmed=true only after operator confirms cost."
                ),
                "reason_code": "PRO_CONFIRMATION_REQUIRED",
            }
        return {
            "ok": True, "kind": "deepseek", "lane": raw, "policy": pol,
            "requested_model_id": POLICY_TO_MODEL[pol],
            "error": None, "reason_code": None,
        }

    # Uppercase logical policies passed as lane
    up = raw.upper()
    if up in ("FAST", "FAST_THINK"):
        return {
            "ok": True, "kind": "deepseek", "lane": raw, "policy": up,
            "requested_model_id": POLICY_TO_MODEL[up],
            "error": None, "reason_code": None,
        }
    if up in ("PRO", "PRO_THINK", "PRO_MAX"):
        if not operator_confirmed:
            code = "PRO_MAX_CONFIRMATION_REQUIRED" if up == "PRO_MAX" else "PRO_CONFIRMATION_REQUIRED"
            return {
                "ok": False, "kind": "deepseek", "lane": raw, "policy": up,
                "requested_model_id": POLICY_TO_MODEL[up],
                "error": f"{code}: paid Pro path requires operator_confirmed=true",
                "reason_code": code,
            }
        return {
            "ok": True, "kind": "deepseek", "lane": raw, "policy": up,
            "requested_model_id": POLICY_TO_MODEL[up],
            "error": None, "reason_code": None,
        }

    return {
        "ok": False, "kind": None, "lane": raw, "policy": None,
        "requested_model_id": None,
        "error": (
            "lane must be grok, chatgpt, deepseek-flash / fast / fast_think "
            "(or PRO family with operator_confirmed)"
        ),
        "reason_code": "LANE_NOT_ALLOWED",
    }


def deepseek_readiness_rows() -> list[dict[str, Any]]:
    """Structured DeepSeek readiness for UI. Never include env var names or secret values."""
    key_present = False
    models_ok = False
    probe_error = None
    try:
        from lib.llm_model_registry import get_deepseek_api_key
        key, _name, _legacy = get_deepseek_api_key()
        key_present = bool(key)
        # deliberately drop _name — never surface to browser
    except Exception as e:
        probe_error = type(e).__name__

    if key_present:
        try:
            from lib.deepseek_client import list_models
            info = list_models(timeout=8)
            models_ok = bool(info.get("has_v4_flash") and info.get("has_v4_pro"))
            if not models_ok and not probe_error:
                probe_error = "models_missing_v4_ids"
        except Exception as e:
            probe_error = type(e).__name__
            # key present but probe failed — still report auth configured generically
            try:
                import llm_lane
                models_ok = bool(llm_lane.available("deepseek-flash"))
            except Exception:
                models_ok = False

    if models_ok and key_present:
        ready, status, hint = True, "ready", None
        reason_code = None
    elif not key_present:
        ready, status = False, "offline"
        hint = "Provider credentials are not configured for this host process."
        reason_code = "PROVIDER_AUTH_NOT_CONFIGURED"
    else:
        ready, status = False, "offline"
        hint = "Provider is configured but the model capability probe failed."
        reason_code = "PROVIDER_PROBE_FAILED"

    base = {
        "kind": "metered_api",
        "billing": "metered",
        "ready": ready,
        "status": status,
        "authenticated": key_present,  # boolean only — not which env
        "reachable": ready or key_present,
        "hint": hint,
        "reason_code": reason_code,
        # never include probe_error string that might leak paths; keep generic
        "token_expired": False,
    }
    return [
        {**base, "lane": "deepseek-flash", "label": "DeepSeek V4 Flash"},
        {**base, "lane": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
    ]
