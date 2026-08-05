"""Additive /api/v3/watch/* Rockville endpoints (shadow-safe).

Does not replace /api/v2 consumers. Feature flags gate paid/visible surfaces.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

ET = ZoneInfo("America/New_York")
RUNTIME = PROJECT_ROOT / "data" / "runtime" / "rockville"
RUNTIME.mkdir(parents=True, exist_ok=True)


def _flags() -> dict[str, bool]:
    from lib.rockville.model_policy import feature_flags
    return feature_flags()


def _project(packet: dict, action_policy: dict | None = None) -> dict:
    from lib.rockville.decision_projection import project_watch_decision
    return project_watch_decision(packet, action_policy, symbol=packet.get("symbol"))


def get_priority(db_query: Callable | None = None) -> dict[str, Any]:
    """Compact card list for Watch priority rail."""
    flags = _flags()
    cards = []
    # Prefer runtime snapshot if present (fixture/shadow path)
    snap = RUNTIME / "priority_cards.json"
    if snap.exists():
        try:
            cards = json.loads(snap.read_text(encoding="utf-8"))
        except Exception:
            cards = []
    # Always include FTH fixture as regression shadow when empty or forced
    if not cards:
        fixture = PROJECT_ROOT / "tests" / "fixtures" / "rockville" / "ROCKVILLE_FTH_REGRESSION_FIXTURE.json"
        if fixture.exists():
            fx = json.loads(fixture.read_text(encoding="utf-8"))
            dec = _project(fx["packet"], fx.get("action_policy"))
            cards = [{
                "symbol": "FTH",
                "company": fx.get("company"),
                "sector": fx.get("sector"),
                "decision": dec,
                "shadow": True,
            }]
    return {
        "ok": True,
        "schema": "watch_priority.v1",
        "flags": flags,
        "generated_at": datetime.now(ET).isoformat(),
        "cards": cards,
        "count": len(cards),
    }


def get_symbol(symbol: str, db_query: Callable | None = None) -> dict[str, Any]:
    sym = (symbol or "").upper().strip()
    fixture = PROJECT_ROOT / "tests" / "fixtures" / "rockville" / "ROCKVILLE_FTH_REGRESSION_FIXTURE.json"
    if sym == "FTH" and fixture.exists():
        fx = json.loads(fixture.read_text(encoding="utf-8"))
        dec = _project(fx["packet"], fx.get("action_policy"))
        return {
            "ok": True,
            "symbol": sym,
            "decision": dec,
            "packet_ref": "fixture:ROCKVILLE_FTH_REGRESSION_FIXTURE",
            "reflective_review": _load_review(sym),
            "flags": _flags(),
        }
    # Shadow: try runtime store
    path = RUNTIME / "symbols" / f"{sym}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        packet = data.get("packet") or data
        dec = _project(packet, data.get("action_policy"))
        return {
            "ok": True,
            "symbol": sym,
            "decision": dec,
            "reflective_review": data.get("reflective_review") or _load_review(sym),
            "flags": _flags(),
        }
    return {"ok": False, "error": "symbol_not_in_rockville_shadow", "symbol": sym, "flags": _flags()}


def get_reviews(symbol: str) -> dict[str, Any]:
    return {
        "ok": True,
        "symbol": (symbol or "").upper(),
        "review": _load_review((symbol or "").upper()),
        "flags": _flags(),
    }


def _load_review(symbol: str) -> dict | None:
    path = RUNTIME / "reviews" / f"{symbol.upper()}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


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
    # Mark prior vs current
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
        "scheduler_state_exists": (RUNTIME / "cio_scheduler_state.json").exists(),
    }


def get_universe_health() -> dict[str, Any]:
    pri = get_priority()
    states: dict[str, int] = {}
    for c in pri.get("cards") or []:
        st = ((c.get("decision") or {}).get("primary_state")) or "UNKNOWN"
        states[st] = states.get(st, 0) + 1
    return {
        "ok": True,
        "card_count": pri.get("count", 0),
        "state_counts": states,
        "flags": _flags(),
    }


def post_cio_deep_review(body: dict | None = None) -> dict[str, Any]:
    """Operator-confirmed only. Does not call provider unless flag + confirmation."""
    flags = _flags()
    body = body or {}
    if not flags.get("watch_cio_deep_review_enabled"):
        return {
            "ok": False,
            "error": "COST_CAP_BLOCKED",
            "message": "watch_cio_deep_review_enabled is false",
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
            "flags": flags,
        }
    # Shadow: do not invoke paid provider in default off/shadow rollout
    return {
        "ok": False,
        "error": "SHADOW_NO_PROVIDER_CALL",
        "message": "Deep review accepted confirmation path but provider call is gated until rollout step 5+",
        "request_id": str(uuid.uuid4()),
        "flags": flags,
    }


def run_cio_scheduler_tick(material_hash: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Idempotent scheduler tick — zero provider calls when no material change."""
    from lib.rockville.cio_scheduler import (
        evaluate_cio_trigger,
        publish_no_material_change,
        mark_in_flight,
    )
    from lib.rockville.model_policy import feature_flags, resolve_policy

    flags = feature_flags()
    mh = material_hash or "0" * 64
    decision = evaluate_cio_trigger(mh, force=force)
    if decision.action == "SKIP_NO_MATERIAL_CHANGE":
        art = publish_no_material_change(mh)
        return {"ok": True, "decision": decision.__dict__, "artifact": art, "provider_calls": 0}
    if decision.action != "RUN":
        return {"ok": True, "decision": decision.__dict__, "provider_calls": 0}
    if not flags.get("watch_cio_daily_enabled") and not force:
        return {
            "ok": True,
            "decision": decision.__dict__,
            "provider_calls": 0,
            "message": "would RUN but watch_cio_daily_enabled=false (shadow)",
        }
    # Paid path still gated — record in-flight then fail closed without silent fallback
    mark_in_flight(decision)
    pol = resolve_policy("CIO_DAILY_PRO")
    return {
        "ok": False,
        "error": "COST_CAP_BLOCKED",
        "message": "CIO_DAILY_PRO enabled flag path requires governed provider runner (rollout step 5+)",
        "decision": decision.__dict__,
        "policy": pol,
        "provider_calls": 0,
    }


# Route table for api_v2 registration
ROUTES = {
    "/api/v3/watch/priority": lambda query=None: get_priority(),
    "/api/v3/watch/pipeline-health": lambda query=None: get_pipeline_health(),
    "/api/v3/watch/universe-health": lambda query=None: get_universe_health(),
    "/api/v3/watch/cio/latest": lambda query=None: get_cio_latest(),
    "/api/v3/watch/cio/history": lambda query=None: get_cio_history(
        int((query or {}).get("limit", [14])[0]) if isinstance((query or {}).get("limit"), list)
        else int((query or {}).get("limit") or 14)
    ),
}
