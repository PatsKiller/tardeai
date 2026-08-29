"""1-hop graph impact for HELD non-dust names only. Wave 3C item 4.

`cio_graph_impact` already computes same-sector held neighbours at HOP=1 with
a cap. This adds the eligibility rule the brief asks for and records *why* a
subject was skipped, rather than returning an empty neighbour list that reads
identically to "no neighbours found".

Skipped by construction: CASH and cash-equivalents, dust residuals (aggregate
market value under the $50/ticker policy), non-ticker instrument ids
(CUSIP/ISIN), and TEST symbols. None of these are entities a sector graph can
say anything about, and minting graph identity for them is how a watch book
acquires members nobody added.
"""
from __future__ import annotations

from typing import Any, Optional

GRAPH_IMPACT_HELD_SCHEMA = "CIOGraphImpactHeld@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
HOP = 1

TEST_PREFIXES = ("TEST", "ZZZ", "DUMMY")

SKIP_CASH = "cash_or_non_entity"
SKIP_DUST = "dust_residual"
SKIP_NOT_TICKER = "not_a_ticker"
SKIP_TEST = "test_symbol"
SKIP_NOT_HELD = "not_held"


def _eligibility(symbol: str, *, held: set[str], dust: set[str],
                 cash_symbols: set[str]) -> Optional[str]:
    sym = str(symbol or "").strip().upper()
    if not sym:
        return SKIP_NOT_TICKER
    if sym in cash_symbols or sym == "CASH":
        return SKIP_CASH
    if any(sym.startswith(p) for p in TEST_PREFIXES):
        return SKIP_TEST
    try:
        from scripts.lib.holdings_universe import classify_instrument_id

        # The classifier NAMES the id types it recognises (CUSIP, ISIN) and
        # returns UNKNOWN_INSTRUMENT_ID for anything else — including ordinary
        # tickers. So exclude the recognised non-ticker types rather than
        # requiring a positive "ticker" verdict it never emits.
        if str(classify_instrument_id(sym) or "").upper() in {"CUSIP", "ISIN", "SEDOL"}:
            return SKIP_NOT_TICKER
    except Exception:
        pass
    if sym in dust:
        return SKIP_DUST
    if held and sym not in held:
        return SKIP_NOT_HELD
    return None


def build(*, symbols: list[str], holdings: Optional[dict[str, Any]] = None,
          held: Optional[set[str]] = None, dust: Optional[set[str]] = None,
          cash_symbols: Optional[set[str]] = None,
          cap: int = 5) -> dict[str, Any]:
    """1-hop neighbours for eligible subjects; explicit skips for the rest."""
    from scripts.lib.cio_graph_impact import build_sector_index, graph_impact_for

    held_set = {str(s).upper() for s in (held or set())}
    dust_set = {str(s).upper() for s in (dust or set())}
    cash_set = {str(s).upper() for s in (cash_symbols or {"CASH", "USD"})}

    index = build_sector_index(holdings, eligible=held_set or None)
    impacts: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for raw in symbols or []:
        sym = str(raw or "").strip().upper()
        reason = _eligibility(sym, held=held_set, dust=dust_set,
                              cash_symbols=cash_set)
        if reason:
            skipped.append({"symbol": sym or None, "skip_reason": reason,
                            "graph_impact": None})
            continue
        impacts.append({
            "symbol": sym,
            "hop": HOP,
            "graph_impact": graph_impact_for(sym, holdings=holdings,
                                             index=index, cap=cap),
        })
    return {
        "schema": GRAPH_IMPACT_HELD_SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "hop": HOP,
        "cap": cap,
        "impacts": impacts,
        "skipped": skipped,
        "counts": {
            "considered": len(symbols or []),
            "with_impact": len(impacts),
            "skipped": len(skipped),
            "by_skip_reason": {
                r: sum(1 for s in skipped if s["skip_reason"] == r)
                for r in sorted({s["skip_reason"] for s in skipped})
            },
        },
        "mints_watch_identity": False,
        "note": ("CASH, dust, non-ticker ids and TEST symbols are skipped with "
                 "a reason rather than returned as empty neighbour lists."),
    }
