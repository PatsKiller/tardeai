"""1-hop same-sector neighbours for held names (Wave 2 slices 15 / 16).

READ_ONLY_ADVISORY. MBI=0. Class **D** — context, never an action.

The edge is deliberately the weakest honest one available: two names are 1-hop
neighbours when the *existing* holdings sector resolution
(`resolved_sector_contributors`) places them in the same sector. No new store,
no new sector vendor, no invented relationship. If the sector map is missing the
result is an explicit DATA_UNAVAILABLE, never a guess.

Scope is bounded on purpose (slice 16): graph_impact is attached to
**S6_CONCENTRATION_OR_DISPOSITION names only**. A concentration/disposition
question is the one place a "what else do I own in this sector" answer changes
the operator's reading. Attaching it everywhere would be decoration.

Dust is excluded on both sides: a residual share neither has neighbours nor
counts as one.
"""
from __future__ import annotations

from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CIOGraphImpact@v1"
S6 = "S6_CONCENTRATION_OR_DISPOSITION"
NEIGHBOR_CAP = 5
HOP = 1


def sector_contributors(holdings: Optional[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    raw = (holdings or {}).get("resolved_sector_contributors")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for sector, rows in raw.items():
        if not isinstance(rows, list):
            continue
        keep = [r for r in rows if isinstance(r, dict) and r.get("symbol")]
        if keep:
            out[str(sector)] = keep
    return out


def _value(row: dict[str, Any]) -> float:
    try:
        return float(row.get("value") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_sector_index(
    holdings: Optional[dict[str, Any]],
    *,
    eligible: Optional[set[str]] = None,
) -> dict[str, Any]:
    """symbol → sectors, sector → symbols, and each symbol's value per sector."""
    by_symbol: dict[str, set[str]] = {}
    by_sector: dict[str, set[str]] = {}
    value: dict[tuple[str, str], float] = {}
    for sector, rows in sector_contributors(holdings).items():
        for r in rows:
            sym = str(r.get("symbol") or "").strip().upper()
            if not sym or (eligible is not None and sym not in eligible):
                continue
            by_symbol.setdefault(sym, set()).add(sector)
            by_sector.setdefault(sector, set()).add(sym)
            key = (sym, sector)
            value[key] = value.get(key, 0.0) + _value(r)
    return {"by_symbol": by_symbol, "by_sector": by_sector, "value": value}


def graph_impact_for(
    symbol: str,
    *,
    holdings: Optional[dict[str, Any]] = None,
    index: Optional[dict[str, Any]] = None,
    eligible: Optional[set[str]] = None,
    cap: int = NEIGHBOR_CAP,
) -> dict[str, Any]:
    """Same-sector held neighbours of `symbol`, capped and deterministic.

    Ranked by shared-sector count, then by the neighbour's summed contribution
    across those shared sectors, then alphabetically — so the same book always
    produces the same list.
    """
    sym = str(symbol or "").strip().upper()
    idx = index if index is not None else build_sector_index(holdings, eligible=eligible)
    by_symbol: dict[str, set[str]] = idx["by_symbol"]
    by_sector: dict[str, set[str]] = idx["by_sector"]
    values: dict[tuple[str, str], float] = idx["value"]

    base = {
        "schema": SCHEMA,
        "symbol": sym,
        "hop": HOP,
        "cap": int(cap),
        "class": "D",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "edge": "same_sector_held",
        "source": "holdings.resolved_sector_contributors",
    }
    if not by_sector:
        return {**base, "available": False, "quality": "DATA_UNAVAILABLE",
                "reason": "no resolved_sector_contributors on holdings",
                "sectors": [], "neighbors": [], "neighbor_n": 0}
    sectors = sorted(by_symbol.get(sym, set()))
    if not sectors:
        return {**base, "available": True, "quality": "NO_SECTOR_FOR_SYMBOL",
                "reason": f"{sym} not present in the resolved sector map",
                "sectors": [], "neighbors": [], "neighbor_n": 0}

    shared: dict[str, list[str]] = {}
    for sector in sectors:
        for other in by_sector.get(sector, set()):
            if other == sym:
                continue
            shared.setdefault(other, []).append(sector)

    ranked = sorted(
        shared.items(),
        key=lambda kv: (
            -len(kv[1]),
            -sum(values.get((kv[0], s), 0.0) for s in kv[1]),
            kv[0],
        ),
    )
    neighbors = [
        {
            "symbol": other,
            "shared_sectors": sorted(secs),
            "shared_sector_n": len(secs),
            "shared_value": round(sum(values.get((other, s), 0.0) for s in secs), 2),
            "class": "D",
        }
        for other, secs in ranked[: max(0, int(cap))]
    ]
    return {
        **base,
        "available": True,
        "quality": "OK",
        "reason": None,
        "sectors": sectors,
        "neighbors": neighbors,
        "neighbor_n": len(neighbors),
        "neighbor_total": len(ranked),
        "truncated": len(ranked) > len(neighbors),
    }


# ── slice 16: S6 names only ──────────────────────────────────────────────────

def s6_symbols(plans: Optional[list[dict[str, Any]]]) -> list[str]:
    """Symbols carrying an open S6 plan. Nothing else is in scope."""
    out: list[str] = []
    for p in plans or []:
        if not isinstance(p, dict) or p.get("situation_type") != S6:
            continue
        for s in p.get("symbols") or []:
            sym = str(s).strip().upper()
            if sym and sym not in out:
                out.append(sym)
    return sorted(out)


def build_graph_impact_for_s6(
    *,
    plans: Optional[list[dict[str, Any]]] = None,
    holdings: Optional[dict[str, Any]] = None,
    cap: int = NEIGHBOR_CAP,
) -> dict[str, Any]:
    """graph_impact keyed by S6 symbol. Non-S6 names get nothing, by design."""
    from scripts.lib.cio_investment_product import (
        dust_symbols,
        held_equity_symbols_nondust,
    )

    eligible = set(held_equity_symbols_nondust(holdings))
    dust = sorted(dust_symbols(holdings))
    index = build_sector_index(holdings, eligible=eligible)
    syms = s6_symbols(plans)
    items = {}
    skipped: list[dict[str, str]] = []
    for sym in syms:
        if sym not in eligible:
            skipped.append({
                "symbol": sym,
                "reason": "dust_residual" if sym in set(dust) else "not_held_non_dust",
            })
            continue
        items[sym] = graph_impact_for(sym, index=index, cap=cap)
    return {
        "schema": "CIOGraphImpactS6@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "scope": "S6_CONCENTRATION_OR_DISPOSITION names only",
        "hop": HOP,
        "cap": int(cap),
        "s6_symbols": syms,
        "s6_symbol_n": len(syms),
        "attached_n": len(items),
        "items": items,
        "skipped": skipped,
        "sector_map_available": bool(index["by_sector"]),
        "class": "D",
        "note": (
            "1-hop same-sector held neighbours from the existing holdings sector "
            "resolution. Context only — never an action, never a new store."
        ),
    }
