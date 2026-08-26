"""CIO live-delivery audit and test-sink. Does not change the canary."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.atomic_json_store import append_jsonl
from scripts.lib.operator_human_renderer import looks_like_raw_json, render_decision

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def _env(name: str) -> str:
    v = os.environ.get(name)
    return v.strip() if v else ""


def audit_delivery_flags() -> dict[str, Any]:
    authorize = _env("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY") or "unset"
    interdict = _env("CIO_TELEGRAM_INTERDICT") or "unset"
    canary = _env("CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY") or "0"
    try:
        from scripts.lib.cio_delivery_mode import classify_delivery_mode
        mode = classify_delivery_mode(os.environ) or {}
        delivery_mode = mode.get("CIO_DELIVERY_MODE") or mode.get("mode")
    except Exception:
        delivery_mode = "unknown"
    canary_on = canary in {"1", "true", "TRUE", "yes", "on"}
    live_required = not canary_on
    return {
        "schema": "CIOLiveDeliveryAudit@v1",
        "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY": authorize,
        "CIO_TELEGRAM_INTERDICT": interdict,
        "CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY": canary if canary else "0",
        "delivery_mode": delivery_mode,
        "LIVE_CIO_DELIVERY_AUTHORIZATION_REQUIRED": live_required,
        "authorization_one_liner": (
            "I authorize enabling CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY=1 for "
            "READ_ONLY_ADVISORY CIO material-financial Telegram notifications. "
            "This authorization is notification-only and does not authorize orders, "
            "broker actions, stops, risk changes, or trading."
        ),
        "canary_changed": False,
        "orders": 0,
        "broker_mutations": 0,
        "stop_mutations": 0,
        "risk_mutations": 0,
        "READ_ONLY_ADVISORY": True,
        "authority": AUTHORITY,
        "financial_action": False,
        "note": "Audit only. Canary is not flipped in this tranche.",
    }


def write_test_sink(decision: dict[str, Any], *, path: Path, kind: str = "IMMEDIATE") -> dict[str, Any]:
    """Write a human message to a test sink. No Telegram. No broker."""
    text = render_decision(decision)
    rec = {
        "schema": "CIOTestSink@v1",
        "kind": kind,
        "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision_id": decision.get("decision_id"),
        "generation_id": decision.get("generation_id"),
        "text": text,
        "raw_json": looks_like_raw_json(text),
        "broker_call": False,
        "order_execution": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    append_jsonl(path, rec)
    return rec
