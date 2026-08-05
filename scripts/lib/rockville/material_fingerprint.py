"""watch_material_fingerprint.v1 — decision-relevant only (not every quote tick)."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def _hash(obj: Any) -> str:
    return hashlib.sha256(_stable(obj).encode("utf-8")).hexdigest()


def _zone_cross(prev_price: float | None, price: float | None, zone: dict | None) -> str:
    if price is None or not zone:
        return "none"
    lo = zone.get("lo") or zone.get("low")
    hi = zone.get("hi") or zone.get("high")
    try:
        lo_f = float(lo) if lo is not None else None
        hi_f = float(hi) if hi is not None else None
        p = float(price)
    except (TypeError, ValueError):
        return "none"
    if lo_f is not None and hi_f is not None:
        inside = lo_f <= p <= hi_f
        if prev_price is not None:
            try:
                prev_in = lo_f <= float(prev_price) <= hi_f
                if prev_in != inside:
                    return "entered" if inside else "exited"
            except (TypeError, ValueError):
                pass
        return "inside" if inside else "outside"
    return "none"


def build_symbol_material_fingerprint(symbol_payload: dict) -> dict:
    """Build decision-relevant fingerprint fields for one symbol.

    Excludes ordinary quote noise unless a transition field is set.
    """
    p = symbol_payload or {}
    symbol = str(p.get("symbol") or "").upper()
    decision = p.get("decision") or {}
    validation = p.get("validation") or p.get("ticket_validation") or {}
    quality = p.get("quality") or p.get("quality_admission") or {}
    ownership = p.get("ownership") or {}
    freshness = p.get("freshness") or {}
    tech = p.get("technical") or p.get("technicals") or {}
    fund = p.get("fundamentals") or {}
    cat = p.get("catalysts") or p.get("events") or {}
    position = p.get("position") or {}
    risk = p.get("risk") or p.get("account_constraints") or {}
    reflective = p.get("reflective_review") or {}
    contract = p.get("contract") or p.get("current_actionable_plan") or {}

    # material transitions only (caller may precompute)
    transitions = p.get("material_transitions") or {}
    price = p.get("last") or p.get("price")
    prev_price = p.get("prev_close") or p.get("previous_price")
    zone = p.get("watch_zone") or contract.get("entry_zone")
    zone_state = transitions.get("zone") or _zone_cross(prev_price, price, zone if isinstance(zone, dict) else None)

    material = {
        "schema_version": "watch_material_fingerprint.v1",
        "symbol": symbol,
        "classification": p.get("classification") or p.get("asset_type"),
        "held": bool(ownership.get("held") or p.get("held")),
        "favorite": bool(p.get("favorite") or ownership.get("favorite")),
        "alert": bool(p.get("alert")),
        "promoted": bool(p.get("promoted")),
        "primary_state": decision.get("primary_state") or p.get("primary_state"),
        "strategy_family": decision.get("selected_strategy_family") or p.get("selected_family"),
        "proposal_eligibility": bool(decision.get("proposal_allowed") if "proposal_allowed" in decision else p.get("proposal_allowed")),
        "contract_hash": validation.get("ticket_hash") or contract.get("ticket_hash") or _hash({
            k: contract.get(k) for k in ("entry_zone", "trigger", "invalidation", "stop_price", "targets")
        }) if contract else None,
        "validation_verdict": validation.get("state") or validation.get("verdict"),
        "blocker_codes": sorted({
            str(b.get("code") if isinstance(b, dict) else b)
            for b in (quality.get("blockers") or decision.get("blockers") or [])
        }),
        "zone_or_trigger_state": zone_state if zone_state != "none" else transitions.get("trigger") or transitions.get("invalidation") or "stable",
        "technical_regime": tech.get("regime") or tech.get("trend"),
        "pattern_state": tech.get("pattern") or tech.get("pattern_state"),
        "support_resistance_hash": _hash(tech.get("sr") or tech.get("support_resistance") or {}),
        "fundamental_snapshot_hash": _hash({
            k: fund.get(k) for k in ("pe", "float", "market_cap", "sector", "industry", "short_float")
            if k in fund
        } or fund),
        "catalyst_snapshot_hash": _hash(cat),
        "position_protection_hash": _hash({
            k: position.get(k) for k in ("shares", "stop", "protection_state", "cost_basis")
            if k in position
        } or position),
        "risk_constraint_hash": _hash(risk),
        "freshness_state": freshness.get("state") or p.get("data_state"),
        "reflective_review_hash": reflective.get("snapshot_hash") or (
            _hash(reflective) if reflective else None
        ),
    }
    material["material_fingerprint"] = _hash(material)
    return material


def build_watchlist_material_hash(symbol_fingerprints: list[dict]) -> str:
    """Global hash = SHA256(sorted(symbol + material_fingerprint))."""
    parts = []
    for fp in symbol_fingerprints:
        sym = str(fp.get("symbol") or "").upper()
        mh = fp.get("material_fingerprint") or ""
        parts.append(f"{sym}:{mh}")
    parts.sort()
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def is_quote_noise_only(prev_fp: dict | None, new_fp: dict | None) -> bool:
    """True if only non-material fields differ (quote noise)."""
    if not prev_fp or not new_fp:
        return False
    # compare material fingerprint identity
    return prev_fp.get("material_fingerprint") == new_fp.get("material_fingerprint")
