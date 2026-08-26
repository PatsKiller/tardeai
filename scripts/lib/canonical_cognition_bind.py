"""Bind sector / industry / catalyst events into CIOOperatorProduct sections.

The operator should see exposure-aware prose, not a bare LAGGING→LEADING tick.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def _exposure_pct(holdings: list[dict[str, Any]], sector: str | None, industry: str | None) -> float:
    total = 0.0
    matched = 0.0
    want_s = (sector or "").lower()
    want_i = (industry or "").lower()
    for h in holdings:
        if not isinstance(h, dict) or h.get("is_cash"):
            continue
        mv = float(h.get("market_value") or 0)
        total += mv
        hs = str(h.get("sector") or "").lower()
        hi = str(h.get("industry") or "").lower()
        if want_s and want_s in hs:
            matched += mv
        elif want_i and want_i in hi:
            matched += mv
    if total <= 0:
        return 0.0
    return round(100.0 * matched / total, 1)


def sector_delta_to_product(
    event: dict[str, Any],
    *,
    holdings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sector = event.get("sector") or event.get("industry")
    frm = event.get("from") or event.get("from_state")
    to = event.get("to") or event.get("to_state")
    held = list(event.get("held") or [])
    pct = event.get("exposure_pct")
    if pct is None:
        pct = _exposure_pct(list(holdings or []), event.get("sector"), event.get("industry"))
    names = ", ".join(str(s) for s in held[:6]) if held else "no current holdings tagged"
    prose = (
        f"{sector} moved {frm}→{to}. "
        f"You have {pct}% exposure ({names}). "
        "No portfolio change recommended unless the CIO decision list says otherwise."
    )
    return {
        "schema": "SectorResearchDelta@v1",
        "sector": sector,
        "industry": event.get("industry"),
        "from_state": frm,
        "to_state": to,
        "exposure_pct": pct,
        "affected_holdings": held,
        "prose": prose,
        "cio_decision": "NO_ACTION",
        "authority": AUTHORITY,
        "financial_action": False,
    }


def catalyst_to_product(event: dict[str, Any]) -> dict[str, Any]:
    entity = event.get("entity") or event.get("symbol")
    return {
        "schema": "CatalystBinding@v1",
        "entity": entity,
        "catalyst": event.get("catalyst") or event.get("title") or event.get("type"),
        "when": event.get("when") or event.get("date") or event.get("as_of"),
        "next_review": event.get("next_review"),
        "traceable_to_entity": bool(entity),
        "authority": AUTHORITY,
        "financial_action": False,
    }
