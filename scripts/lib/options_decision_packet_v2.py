"""OptionsDecisionPacket@v2 adapter.

Adds research-universe and contract-honesty fields without changing v1.  The
packet is advisory-only and intentionally has no sizing or execution fields.
"""
from __future__ import annotations

from typing import Any

from .options_decision_packet import build_options_decision_packet

SCHEMA = "OptionsDecisionPacket@v2"
_FORBIDDEN = frozenset({"shares", "qty", "size_usd", "target_weight_pct", "order", "execution"})


def _first_block(row: dict[str, Any], packet: dict[str, Any]) -> str | None:
    blocks = (row.get("enterprise") or {}).get("blocks") or row.get("blocks") or []
    if blocks:
        first = blocks[0]
        return str(first.get("reason") or first.get("code") or "") if isinstance(first, dict) else str(first)
    notes = (packet.get("comparison") or {}).get("stock_play", {}).get("risk_notes") or []
    return str(notes[0]) if notes else None


def build_options_decision_packet_v2(row: dict[str, Any], *, comparison: dict[str, Any] | None = None, memo: dict[str, Any] | None = None, research: dict[str, Any] | None = None, generated_at: str | None = None) -> dict[str, Any]:
    v1 = build_options_decision_packet(row, comparison=comparison, generated_at=generated_at)
    cmp = comparison or v1.get("comparison") or {}
    opt = cmp.get("options_play") or {}
    comp = cmp.get("comparison") or {}
    memo = memo or {}
    thesis = cmp.get("thesis") or {}
    research = research or {}
    max_profit = opt.get("max_profit")
    max_loss = opt.get("maximum_risk")
    rr = comp.get("reward_to_risk")
    contract = {
        "max_gain": max_profit,
        "max_loss": max_loss,
        "breakeven": row.get("breakeven"),
        "probability_of_profit": opt.get("probability_of_success"),
        "delta": row.get("delta"), "gamma": row.get("gamma"),
        "theta": row.get("theta"), "vega": row.get("vega"), "rho": row.get("rho"),
        "iv_rank": row.get("iv_rank"), "iv_percentile": row.get("iv_percentile"),
        "open_interest": row.get("oi"), "volume": row.get("volume"),
        "liquidity": opt.get("liquidity_status"),
        "spread_cost": row.get("spread_cost") or row.get("bid_ask_spread_pct"),
    }
    out = {
        **v1,
        "schema": SCHEMA,
        "research": {
            "source_lanes": list(research.get("source_lanes") or row.get("source_lanes") or []),
            "status": research.get("research_status") or row.get("research_status") or "research_required",
            "artifact_id": research.get("research_artifact_id") or row.get("research_artifact_id"),
            "why_this_name": research.get("summary") or row.get("summary") or memo.get("thesis", {}).get("why_now"),
            "as_of": research.get("evaluated_at") or row.get("research_as_of"),
        },
        "decision": {
            "why_option_instead_of_stock": memo.get("thesis", {}).get("why_option_instead_of_stock") or opt.get("why_option_instead_of_stock"),
            "catalyst": memo.get("thesis", {}).get("catalyst", "missing"),
            "timeframe": memo.get("thesis", {}).get("timeframe") or row.get("dte"),
            "reward_to_risk": {"value": rr, "basis": "max_profit_divided_by_max_loss"},
            "expected_value": row.get("expected_value") if row.get("expected_value") is not None else opt.get("expected_return"),
            "first_hard_block": _first_block(row, v1),
            "hard_blocks": list((row.get("enterprise") or {}).get("blocks") or row.get("blocks") or []),
            "size": {"status": "not_sized", "display": "Not sized"},
        },
        "structures": memo.get("structures") or [],
        "contract": contract,
        "analysis_lines": {
            "risk": memo.get("committee", {}).get("risk_officer"),
            "options": memo.get("committee", {}).get("options_strategist"),
            "macro": memo.get("committee", {}).get("macro_analyst"),
            "quant": memo.get("committee", {}).get("quant_analyst"),
        },
        "cio": {
            "status": (cmp.get("oversight") or {}).get("review_status") or "unreviewed",
            "cio_review_id": (cmp.get("oversight") or {}).get("cio_review_id"),
            "commentary": (cmp.get("oversight") or {}).get("cio_commentary"),
            "bear_case": memo.get("committee", {}).get("cio", {}).get("bear_case"),
            "strongest_opposing_line": memo.get("committee", {}).get("strongest_opposing_argument"),
        },
        "lifecycle": {
            "proposal_state": v1.get("state"),
            "position_state": row.get("lifecycle_phase") or "not_open",
            "primary_bucket": row.get("primary_bucket"),
            "outcome_status": row.get("outcome_status") or "not_validated",
        },
    }
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            bad = _FORBIDDEN.intersection(node)
            if bad:
                raise ValueError(f"behavior fields in options packet v2: {sorted(bad)}")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(out)
    return out
