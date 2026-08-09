"""Additive /api/v3/watch/* Rockville endpoints (shadow-safe).

Live multi-symbol projection from decision_packets. Fixtures are NOT injected
into production responses (tests load fixtures themselves).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

RUNTIME = PROJECT_ROOT / "data" / "runtime" / "rockville"
RUNTIME.mkdir(parents=True, exist_ok=True)


def _flags() -> dict[str, bool]:
    from lib.rockville.model_policy import feature_flags
    return feature_flags()


def get_priority(db_query: Callable | None = None) -> dict[str, Any]:
    from lib.rockville.live_projection import build_live_cards
    flags = _flags()
    out = build_live_cards()
    out["flags"] = flags
    return out


def get_symbol(symbol: str, db_query: Callable | None = None) -> dict[str, Any]:
    from lib.rockville.live_projection import build_live_symbol
    flags = _flags()
    out = build_live_symbol(symbol)
    out["flags"] = flags
    return out


def get_reviews(symbol: str) -> dict[str, Any]:
    path = RUNTIME / "reviews" / f"{(symbol or '').upper()}.json"
    review = None
    if path.exists():
        try:
            import json
            review = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            review = None
    return {
        "ok": True,
        "symbol": (symbol or "").upper(),
        "review": review,
        "flags": _flags(),
        "note": "No reflective review until paid Flash path enabled",
    }


def get_cio_latest() -> dict[str, Any]:
    from lib.rockville.cio_scheduler import load_latest_artifact
    art = load_latest_artifact()
    flags = _flags()
    if not art:
        return {
            "ok": True,
            "status": "NONE",
            "artifact": None,
            "flags": flags,
            "message": "No CIO digest artifact yet",
        }
    return {"ok": True, "status": art.get("status"), "artifact": art, "flags": flags}


def get_cio_history(limit: int = 14) -> dict[str, Any]:
    from lib.rockville.cio_scheduler import load_history
    return {"ok": True, "artifacts": load_history(limit=limit), "flags": _flags()}


def get_pipeline_health() -> dict[str, Any]:
    from lib.rockville.model_policy import load_policy_file, EXACT_FLASH, EXACT_PRO
    return {
        "ok": True,
        "pipeline": "rockville_watch",
        "exact_models": {"flash": EXACT_FLASH, "pro": EXACT_PRO},
        "policy_version": load_policy_file().get("policy_version"),
        "flags": _flags(),
        "live_projection": True,
        "fixture_injected": False,
    }


def get_universe_health() -> dict[str, Any]:
    pri = get_priority()
    states: dict[str, int] = {}
    for c in pri.get("cards") or []:
        st = c.get("current_state") or ((c.get("decision") or {}).get("primary_state")) or "UNKNOWN"
        states[st] = states.get(st, 0) + 1
    return {
        "ok": True,
        "card_count": pri.get("count", 0),
        "state_counts": states,
        "fixture_injected": pri.get("fixture_injected", False),
        "flags": _flags(),
    }


def post_cio_deep_review(body: dict | None = None) -> dict[str, Any]:
    """Operator-confirmed only. Gated hard when flag is false."""
    flags = _flags()
    body = body or {}
    if not flags.get("watch_cio_deep_review_enabled"):
        return {
            "ok": False,
            "error": "DEEP_REVIEW_GATED",
            "message": "DEEP REVIEW GATED — ROLLOUT NOT ENABLED",
            "provider_call": False,
            "flags": flags,
        }
    if not body.get("operator_confirmed"):
        return {
            "ok": False,
            "error": "OPERATOR_CONFIRMATION_REQUIRED",
            "estimated_cost_usd": body.get("estimated_cost_usd") or 0.15,
            "policy": "CIO_DEEP_REVIEW",
            "model": "deepseek-v4-pro",
            "thinking": True,
            "effort": "max",
            "provider_call": False,
            "flags": flags,
        }
    return {
        "ok": False,
        "error": "SHADOW_NO_PROVIDER_CALL",
        "message": "Confirmation accepted path exists but provider runner is not enabled in foundation rollout",
        "provider_call": False,
        "request_id": None,  # never fabricate provider request IDs
        "flags": flags,
    }
