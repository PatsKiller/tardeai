"""What the Ideas job actually searched. Not a market-wide claim."""
from __future__ import annotations

from typing import Any, Optional

BANNER = (
    "This inventory is not a market-wide completion claim. Coverage includes holdings, active watchlist, re-entry and shared research. "
    "The coverage ledger reports missing inputs and chain evaluation separately; "
    "market-wide discovery is complete only when its source receipt says complete."
)
WATCHLIST_LIMIT = 40
RANKING = "readiness first, then heuristic score within separate desk queues"


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
        for src in set(row.get("source_lanes") or [row.get("source") or "unknown"]):
            by_source[src] = by_source.get(src, 0) + 1
    hold_syms = _syms(holdings)
    screened = len(hold_syms | conv_syms) if inputs_recorded else None
    blocked = sum(1 for row in listed if _blocked(row))
    return {
        "claim": "not_a_market_wide_search",
        "banner": BANNER,
        "screened": screened,
        "inputs_recorded": inputs_recorded,
        "inventory_count": screened,
        "screened_definition": "inventory membership; not completed chain evaluation",
        "source_lane_counts": by_source,
        "sources": {
            "holdings": len(hold_syms) if inputs_recorded else None,
            "layer4_limit": 40,
            "fused_limit": 30,
            "starred_limit": 15,
            "layer4_used": by_source.get("layer4", 0) if inputs_recorded else None,
            "fused_used": by_source.get("fused_signal", 0) if inputs_recorded else None,
            "starred_used": by_source.get("operator_starred", 0) if inputs_recorded else None,
            "entry_state_used": by_source.get("entry_state", 0) if inputs_recorded else None,
            "watchlist_buy_strong_buy_limit": WATCHLIST_LIMIT,
            "watchlist_used": by_source.get("watchlist_buy_strong_buy", 0) if inputs_recorded else None,
            "liquid_options_core_included": False,
        },
        "scored": int(scored),
        "listed": len(listed),
        "blocked": blocked,
        "ranking": RANKING,
    }


def desk_queue(proposal: dict, lanes: list[str]) -> str:
    if proposal.get("strategy") in {"protective_put", "collar"}:
        return "protection"
    if proposal.get("strategy") == "covered_call":
        return "income"
    if set(lanes).intersection({"watchlist", "watchlist_buy_strong_buy", "reentry", "entry_state"}):
        return "watch_reentry"
    return "discovery"


def build_coverage(*, holdings: list[dict], convictions: list[dict], proposals: list[dict],
                   drops: list[dict], chains: dict, source_receipts: dict | None = None) -> dict:
    """One row per underlying, with distinct account lots and complete disposition.

    Membership never implies research validity, chain completeness or tradability.
    ``chains`` is provider coverage metadata, not inferred from candidate counts.
    """
    from .options_research_universe import merge_research_rows

    rows = merge_research_rows([*convictions, *(
        {"symbol": h.get("symbol"), "source": "holdings", "subject_guid": h.get("subject_guid")}
        for h in holdings if not h.get("is_cash"))])
    from collections import defaultdict
    by_symbol, drops_by_symbol, accounts_by_symbol = defaultdict(list), defaultdict(list), defaultdict(dict)
    for p in proposals:
        by_symbol[str(p.get("symbol") or "").upper()].append(p)
    for d in drops:
        drops_by_symbol[str(d.get("symbol") or "").upper()].append(d)
    for h in holdings:
        if h.get("is_cash"):
            continue
        sym = str(h.get("symbol") or "").upper()
        key = h.get("account") or h.get("account_key")
        account = accounts_by_symbol[sym].setdefault(key, {"account": key, "shares": 0, "excluded": True})
        account["shares"] += float(h.get("shares") or h.get("quantity") or 0)
        account["excluded"] = account["excluded"] and bool(h.get("options_desk_excluded"))
    status_counts: dict[str, int] = {}
    for row in rows:
        sym = row["symbol"]
        accounts = list(accounts_by_symbol[sym].values())
        for account in accounts:
            account["covered_call_capacity"] = max(0, int(account["shares"] // 100))
        found = by_symbol[sym]
        reasons = drops_by_symbol[sym]
        chain = chains.get(sym) or {}
        if accounts and all(a["excluded"] for a in accounts) and set(row["source_lanes"]) == {"holdings"}:
            status = "POLICY_EXCLUDED"
        elif chain.get("status") == "UNSUPPORTED":
            status = "UNSUPPORTED"
        elif chain.get("status") in {"ERROR", "PARTIAL", "UNAVAILABLE"}:
            status = "DATA_UNAVAILABLE"
        elif found:
            status = "EVALUATED"
        elif chain.get("status") == "COMPLETE":
            status = "RESEARCH_REQUIRED" if not row.get("research_qualified") else "EVALUATED"
        else:
            status = "PENDING"
        row.update(accounts=accounts, status=status, chain=chain, proposal_count=len(found),
                   ready_count=sum(not _blocked(p) and p.get("approvable") is True for p in found),
                   reasons=reasons, proposal_ids=[p.get("id") for p in found],
                   direction_status="REVIEW_REQUIRED" if row.get("direction_conflict") else "RESOLVED")
        status_counts[status] = status_counts.get(status, 0) + 1
    receipts = source_receipts or {}
    return {"schema": "OptionsCoverage@v1", "inventory_count": len(rows),
            "account_position_count": sum(len(r["accounts"]) for r in rows),
            "status_counts": status_counts, "rows": rows, "source_receipts": receipts,
            "status": "PARTIAL" if any(r.get("status") != "COMPLETE" for r in receipts.values()) else "RECORDED",
            "chain_completed_count": sum(r["chain"].get("status") == "COMPLETE" for r in rows)}
