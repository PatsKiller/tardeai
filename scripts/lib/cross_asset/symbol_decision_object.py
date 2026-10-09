"""Legacy grouped v1 constructor retained for compatibility.

The canonical contract is cross_asset.canonical_decision (v2). This legacy
constructor must not be used to claim account-local coverage or a proven winner.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

SCHEMA = "SymbolDecisionObject@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

REQUIRED_GROUPS = (
    "identity",
    "equity_thesis",
    "research_state",
    "event_state",
    "signal_state",
    "position_state",
    "options_state",
    "cio_state",
    "historical_state",
    "expression_comparison",
    "audit_history",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_symbol_decision(
    symbol: str,
    *,
    subject_guid: str | None = None,
    issuer_guid: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    if not sym:
        raise ValueError("symbol_required")
    ts = as_of or _now()
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "identity": {
            "symbol": sym,
            "subject_guid": subject_guid,
            "issuer_guid": issuer_guid,
            "as_of": ts,
        },
        "equity_thesis": {
            "stance": None,
            "summary": None,
            "conviction": None,
            "invalidation": [],
            "source_refs": [],
            "state": "INSUFFICIENT_DATA",
        },
        "research_state": {
            "status": "unknown",
            "research_id": None,
            "result_id": None,
            "age_hours": None,
            "as_of": None,
        },
        "event_state": {
            "regime": None,
            "catalysts": [],
            "material_flags": [],
        },
        "signal_state": {
            "kind": "none",
            "lane": None,
            "signal_id": None,
            "fired_at": None,
        },
        "position_state": {
            "held_shares": 0.0,
            "accounts": [],
            "coverage_100": False,
            "cash_available": None,
        },
        "options_state": {
            "packets": [],
            "chain_as_of": None,
            "notes": [],
        },
        "cio_state": {
            "situation_ids": [],
            "product_refs": [],
            "advisory_stance": None,
        },
        "historical_state": {
            "prior_decision_ids": [],
            "outcome_refs": [],
        },
        "expression_comparison": {
            "ranked": [],
            "top_family": None,
            "shadow_only": True,
            "as_of": ts,
        },
        "audit_history": [
            {
                "ts": ts,
                "actor": "cross_asset.new_symbol_decision",
                "action": "created",
            }
        ],
    }


def validate_symbol_decision(obj: dict[str, Any]) -> dict[str, Any]:
    """Return {ok, errors[]}. Never raises for shape issues."""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return {"ok": False, "errors": ["not_a_dict"]}
    if obj.get("schema") != SCHEMA:
        errors.append(f"schema_expected_{SCHEMA}")
    if obj.get("authority") != AUTHORITY:
        errors.append("authority_must_be_READ_ONLY_ADVISORY")
    for g in REQUIRED_GROUPS:
        if g not in obj:
            errors.append(f"missing_group:{g}")
            continue
        val = obj.get(g)
        if g == "audit_history":
            if not isinstance(val, list):
                errors.append("audit_history_must_be_list")
        elif not isinstance(val, dict):
            errors.append(f"missing_group:{g}")
    ident = obj.get("identity") if isinstance(obj.get("identity"), dict) else {}
    if not str(ident.get("symbol") or "").strip():
        errors.append("identity.symbol_required")
    return {"ok": not errors, "errors": errors}


def attach_audit(obj: dict[str, Any], *, actor: str, action: str, detail: str | None = None) -> dict[str, Any]:
    out = deepcopy(obj)
    row = {"ts": _now(), "actor": actor, "action": action}
    if detail:
        row["detail"] = detail[:300]
    hist = list(out.get("audit_history") or [])
    hist.append(row)
    # History is durable evidence, not a UI tail. Consumers can page it without
    # destroying older audit entries at an assembly boundary.
    out["audit_history"] = hist
    return out
