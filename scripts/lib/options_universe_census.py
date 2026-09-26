"""What the Ideas job actually searched. Not a market-wide claim."""
from __future__ import annotations

from typing import Any, Optional

BANNER = (
    "This is not a market-wide options search. "
    "These cards were scored from holdings and a short signal list."
)
RANKING = "edge_score among names already in this limited set"


def _syms(rows: list[dict] | None) -> set[str]:
    out = set()
    for row in rows or []:
        if row.get("is_cash"):
            continue
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out.add(sym)
    return out


def _blocked(row: dict) -> bool:
    ent = row.get("enterprise") or {}
    if ent.get("blocks"):
        return True
    if ent.get("live_eligible") is False:
        return True
    return False


def build_universe_census(
    *,
    holdings: Optional[list[dict]] = None,
    convictions: Optional[list[dict]] = None,
    scored: int = 0,
    listed: Optional[list[dict]] = None,
    inputs_recorded: bool = False,
) -> dict[str, Any]:
    """Census for one Ideas run. liquid_options_core is not in this job."""
    listed = list(listed or [])
    by_source: dict[str, int] = {}
    conv_syms: set[str] = set()
    for row in convictions or []:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        conv_syms.add(sym)
        src = str(row.get("source") or "unknown")
        by_source[src] = by_source.get(src, 0) + 1
    hold_syms = _syms(holdings)
    screened = len(hold_syms | conv_syms) if inputs_recorded else None
    blocked = sum(1 for row in listed if _blocked(row))
    return {
        "claim": "not_a_market_wide_search",
        "banner": BANNER,
        "screened": screened,
        "inputs_recorded": inputs_recorded,
        "sources": {
            "holdings": len(hold_syms) if inputs_recorded else None,
            "layer4_limit": 40,
            "fused_limit": 30,
            "starred_limit": 15,
            "layer4_used": by_source.get("layer4", 0) if inputs_recorded else None,
            "fused_used": by_source.get("fused_signal", 0) if inputs_recorded else None,
            "starred_used": by_source.get("operator_starred", 0) if inputs_recorded else None,
            "entry_state_used": by_source.get("entry_state", 0) if inputs_recorded else None,
            "liquid_options_core_included": False,
        },
        "scored": int(scored),
        "listed": len(listed),
        "blocked": blocked,
        "ranking": RANKING,
    }
