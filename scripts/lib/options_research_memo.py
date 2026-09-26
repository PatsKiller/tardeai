"""Investment memo for one options card.

House facts only. A missing catalyst stays missing. Calendar, diagonal, and
collar are not available. This is not a CIO approval and not an order.
"""
from __future__ import annotations

from typing import Any, Optional

STRUCTURES = (
    "long_call",
    "long_put",
    "covered_call",
    "cash_secured_put",
    "debit_spread",
    "credit_spread",
    "calendar_spread",
    "diagonal_spread",
    "collar",
)
ABSENT = frozenset({"calendar_spread", "diagonal_spread", "collar"})
BUILT = frozenset(STRUCTURES) - ABSENT

WHY_OPTION = {
    "covered_call": "You already hold the shares. A call sells some upside for premium. It is not a new investment in the name.",
    "cash_secured_put": "A put is paid to wait. Assignment buys the shares below the current price. It is not the same as buying the shares now.",
    "long_call": "A call risks the premium instead of the full share price. Upside is not capped by a short strike.",
    "long_put": "A put risks the premium to profit if the price falls. It is not a short sale of the shares.",
    "debit_spread": "A debit spread caps both the premium paid and the upside. It costs less than a naked long option and keeps less if the move is large.",
    "credit_spread": "A credit spread collects a limited premium and can lose the width minus that credit. It is not a covered call.",
}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _missing(v: Any) -> Any:
    if v is None or v == "":
        return "missing"
    return v


def _blocks(proposal: dict[str, Any]) -> list[str]:
    raw = (proposal.get("enterprise") or {}).get("blocks") or []
    out = []
    for item in raw:
        if isinstance(item, dict):
            text = str(item.get("reason") or item.get("code") or "")
        else:
            text = str(item)
        if text:
            out.append(text)
    return out


def _structures(selected: str, blocks: list[str], share_count: Optional[float]) -> list[dict[str, str]]:
    rows = []
    for name in STRUCTURES:
        if name in ABSENT:
            rows.append({"structure": name, "status": "not_available", "why": "No generator. Not scored."})
            continue
        if name == selected:
            why = "This is the structure the desk generated."
            if blocks:
                why = "Generated, then blocked: " + blocks[0]
            rows.append({"structure": name, "status": "selected", "why": why})
            continue
        if name == "covered_call" and share_count is not None and share_count < 100:
            rows.append({"structure": name, "status": "rejected", "why": "Fewer than 100 shares in the account."})
            continue
        rows.append({
            "structure": name,
            "status": "not_selected",
            "why": "The desk did not generate this structure for this name on this run.",
        })
    return rows


def build_research_memo(
    proposal: dict[str, Any],
    *,
    census: Optional[dict[str, Any]] = None,
    regime: Optional[str] = None,
    share_count: Optional[float] = None,
) -> dict[str, Any]:
    strategy = str(proposal.get("strategy") or "")
    blocks = _blocks(proposal)
    reasoning = proposal.get("reasoning") or proposal.get("summary")
    pop = _f(proposal.get("pop_pct"))
    max_profit = proposal.get("max_profit")
    max_loss = _f(proposal.get("max_loss"))
    ev = _f(proposal.get("expected_value"))
    rr = _f(proposal.get("risk_reward"))
    if max_profit not in (None, "unlimited") and max_loss not in (None, 0) and max_loss > 0:
        rr = round(_f(max_profit) / max_loss, 4) if _f(max_profit) is not None else rr
    spread = _f(proposal.get("bid_ask_spread_pct"))
    bid = _f(proposal.get("bid"))
    ask = _f(proposal.get("ask"))
    spread_cost = None
    if bid is not None and ask is not None and ask >= bid:
        spread_cost = round(ask - bid, 4)
    invalidation = blocks[0] if blocks else "missing"
    bull = reasoning if reasoning else "missing"
    opposition = blocks[0] if blocks else "no opposing memo on file"
    review_id = proposal.get("cio_review_id")
    return {
        "schema": "OptionsResearchMemo@v1",
        "market_wide_search": False,
        "universe": census or {
            "claim": "not_a_market_wide_search",
            "banner": (
                "This is not a market-wide options search. "
                "These recommendations were generated from a limited watchlist and portfolio-based universe."
            ),
        },
        "rank": {
            "method": "edge_score among names already in this limited set",
            "why_number_one": "missing",
        },
        "thesis": {
            "why_now": _missing(reasoning),
            "why_option_instead_of_stock": WHY_OPTION.get(strategy, "missing"),
            "catalyst": _missing(proposal.get("catalyst")),
            "timeframe": f"{proposal.get('dte')} DTE" if proposal.get("dte") else "missing",
            "reward_to_risk": rr if rr is not None else "missing",
            "probability_weighted_expected_return": ev if ev is not None else "missing",
            "expected_return_basis": "proposal.expected_value" if ev is not None else "missing",
            "invalidation": invalidation,
            "position_size": "not sized",
        },
        "structures": _structures(strategy, blocks, share_count),
        "contract": {
            "expected_value": ev if ev is not None else "missing",
            "max_gain": _missing(max_profit),
            "max_loss": _missing(max_loss),
            "breakeven": _missing(proposal.get("breakeven")),
            "probability_of_profit": pop if pop is not None else "missing",
            "delta": _missing(proposal.get("delta")),
            "gamma": _missing(proposal.get("gamma")),
            "theta": _missing(proposal.get("theta")),
            "vega": _missing(proposal.get("vega")),
            "rho": _missing(proposal.get("rho")),
            "iv_rank": _missing(proposal.get("iv_rank")),
            "iv_percentile": _missing(proposal.get("iv_percentile")),
            "open_interest": _missing(proposal.get("oi")),
            "volume": _missing(proposal.get("volume")),
            "liquidity_score": _missing(proposal.get("liquidity_status")),
            "spread_pct": spread if spread is not None else "missing",
            "spread_cost": spread_cost if spread_cost is not None else "missing",
        },
        "committee": {
            "method": "house_facts",
            "cio": {
                "review_status": "reviewed" if review_id else "unreviewed",
                "cio_review_id": review_id,
                "bear_case": opposition if blocks else "no bear case on file",
                "weak_assumptions": "catalyst missing" if not proposal.get("catalyst") else "catalyst is on the row",
                "priced_in": "missing",
                "market_disagreement": opposition,
                "immediate_rejection": invalidation if blocks else "no hard block on the row",
            },
            "risk_officer": blocks or ["no block codes on the row"],
            "options_strategist": WHY_OPTION.get(strategy, "missing"),
            "macro_analyst": _missing(regime),
            "quant_analyst": {
                "edge_score": _missing(proposal.get("edge_score")),
                "probability_of_profit": pop if pop is not None else "missing",
                "basis": "proposal.pop_pct" if pop is not None else "missing",
            },
            "bull_case": bull,
            "strongest_opposing_argument": opposition,
        },
        "cio_approved": False,
    }
