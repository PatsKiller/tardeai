"""Options desk card semantics — presentation-only labels, gating, and safety copy.

Advisory UI layer: never places orders or changes execution paths.
"""
from __future__ import annotations

from typing import Any, Optional

# Trade verbs that must not appear on blocked / review-only cards.
EXEC_TRADE_ACTIONS = frozenset({
    "sell_covered_call", "sell_put", "buy_put", "buy_call", "sell_credit_spread",
})

CREDIT_STRATEGIES = frozenset({
    "covered_call", "cash_secured_put", "credit_spread",
    "put_credit_spread", "call_credit_spread",
})

DEBIT_STRATEGIES = frozenset({
    "deep_itm_call", "atm_call", "atm_put", "protective_put", "debit_spread",
    "earnings_put_debit_spread", "long_call",
})

DEFAULT_MIN_OI = 50
DEFAULT_MIN_VOLUME = 5
DEFAULT_MAX_SPREAD_PCT = 12.0
OI_ZERO_SCORE_CAP = 45


def option_cashflow_label(
    strategy: str,
    side: str | None = None,
    option_type: str | None = None,
    strategy_family: str | None = None,
) -> str:
    """Human label for total premium cashflow direction."""
    s = (strategy or "").lower()
    if s in ("covered_call", "cash_secured_put"):
        return "Total credit"
    if s in ("credit_spread", "put_credit_spread", "call_credit_spread"):
        return "Net credit"
    if s in ("debit_spread", "earnings_put_debit_spread"):
        return "Net debit"
    if s in ("deep_itm_call", "atm_call", "atm_put", "protective_put", "long_call"):
        return "Total debit"
    # Fallback from side when strategy unknown
    side_u = (side or "").upper()
    if side_u == "SELL":
        return "Total credit"
    if side_u == "BUY":
        return "Total debit"
    return "Total premium"


def cashflow_is_credit(strategy: str, side: str | None = None) -> bool:
    label = option_cashflow_label(strategy, side=side)
    return "credit" in label.lower()


def is_paper_model_row(proposal: dict[str, Any]) -> bool:
    """Paper-model / Alpaca-paper lane — live path blocked, paper testing may continue."""
    if proposal.get("educational_paper_model") or proposal.get("paper_only"):
        return True
    broker = str(proposal.get("broker") or "").lower()
    if broker in ("paper_model", "alpaca"):
        return True
    kind = execution_route_badge(proposal).get("kind")
    return kind in ("alpaca_paper", "paper_model")


def is_desk_trade_blocked(proposal: dict[str, Any]) -> bool:
    """True blocked income/hedge desk row — not paper-model live-path semantics."""
    return is_card_blocked(proposal) and not is_paper_model_row(proposal)


def safety_status_badge(proposal: dict[str, Any]) -> Optional[dict[str, str]]:
    """Header safety chip — paper rows never show generic BLOCKED."""
    if is_paper_model_row(proposal):
        blocks = (proposal.get("enterprise") or {}).get("blocks") or []
        tip = (
            "Blocked from live broker execution — paper testing path remains available."
            + (f" {'; '.join(blocks)}" if blocks else " No live order path until validation gate met.")
        )
        return {
            "label": "NO LIVE PATH",
            "kind": "no_live_path",
            "severity": "amber",
            "tip": tip,
        }
    if is_desk_trade_blocked(proposal):
        blocks = (proposal.get("enterprise") or {}).get("blocks") or []
        return {
            "label": "BLOCKED",
            "kind": "blocked",
            "severity": "danger",
            "tip": "; ".join(blocks) or "Trade actions hidden — review block reason.",
        }
    return None


def is_card_blocked(proposal: dict[str, Any]) -> bool:
    """True when trade actions must be hidden."""
    status = str(proposal.get("status") or proposal.get("queue_status") or "").lower()
    if status == "blocked":
        return True
    if proposal.get("enterprise_blocked"):
        return True
    blocks = (proposal.get("enterprise") or {}).get("blocks") or []
    if blocks:
        return True
    av = str(proposal.get("aegis_verdict") or "").upper()
    if av in ("BLOCK", "BLOCKED", "REJECT"):
        return True
    aegis_st = str(proposal.get("aegis_status") or "").lower()
    if aegis_st in ("block", "blocked", "review_needed", "review-needed"):
        return True
    ens = str(proposal.get("ensemble_verdict") or proposal.get("ensemble_status") or "").upper()
    if ens in ("BLOCK", "BLOCKED", "REJECT"):
        return True
    return False


def execution_route_badge(proposal: dict[str, Any]) -> dict[str, str]:
    """Execution route chip — distinct from data_source (Schwab chain)."""
    if proposal.get("educational_paper_model") or proposal.get("paper_only"):
        if proposal.get("alpaca_paper_enabled") or (proposal.get("meta") or {}).get("alpaca_paper_enabled"):
            return {"label": "Alpaca paper only", "kind": "alpaca_paper"}
        return {"label": "Paper model only", "kind": "paper_model"}
    broker = str(proposal.get("broker") or "").lower()
    if broker == "paper_model":
        return {"label": "Paper model only", "kind": "paper_model"}
    if broker == "fidelity" or proposal.get("execution_mode") == "manual":
        return {"label": "Fidelity manual ticket only", "kind": "fidelity_manual"}
    if broker == "alpaca":
        return {"label": "Alpaca paper only", "kind": "alpaca_paper"}
    ent = proposal.get("enterprise") or {}
    if ent.get("live_eligible") and broker == "schwab":
        return {"label": "Schwab live path · 2FA required", "kind": "schwab_live"}
    if broker == "schwab":
        return {"label": "Review only", "kind": "review_only"}
    return {"label": "Review only", "kind": "review_only"}


def execution_route_note(proposal: dict[str, Any], *, schwab_armed: Optional[bool] = None) -> str:
    """Footer / execution_note copy — never conflate data source with route."""
    route = execution_route_badge(proposal)
    kind = route["kind"]
    if kind == "fidelity_manual":
        return "Manual Fidelity ticket only. Trade AI has no Fidelity broker-submit path."
    if kind == "alpaca_paper":
        return (
            "Alpaca paper only. Simulated order; no live broker order. "
            "Validation credit starts only after fill, close, and outcome reconciliation."
        )
    if kind == "paper_model":
        return "Paper model only. No live order path. Outcomes feed validation."
    if kind == "schwab_live":
        if schwab_armed is False:
            return "Advisory only — run options_pilot_arm --approve to enable live Schwab submit."
        return "Schwab live options path armed. Preflight and per-order 2FA required before submit."
    return "Advisory review only — confirm chain and desk approval before any manual ticket."


def prime_display_label(score: float | None, verdict: str | None = None) -> dict[str, Any]:
    """Map rubric score to operator-facing label (not raw PRIME for low scores)."""
    s = float(score) if score is not None else None
    v = (verdict or "").upper()
    # Normalize legacy verdict constant
    if v == "PAPER_ONLY":
        v = "PAPER_WATCH"
    if s is None:
        return {"label": "—", "short_label": "—", "color": "muted", "verdict": v or None, "show_score": False}
    if s < 50 or v == "NOT_PRIME":
        return {"label": "NOT PRIME", "short_label": f"NOT PRIME {int(round(s))}", "color": "red", "verdict": "NOT_PRIME", "show_score": True}
    if s < 65 or v == "PAPER_WATCH":
        return {"label": "PAPER WATCH", "short_label": f"PAPER WATCH {int(round(s))}", "color": "amber", "verdict": "PAPER_WATCH", "show_score": True}
    if s < 80 or v == "PRIME_FOR_PAPER":
        return {"label": "PRIME FOR PAPER", "short_label": f"PRIME FOR PAPER {int(round(s))}", "color": "teal", "verdict": "PRIME_FOR_PAPER", "show_score": True}
    return {
        "label": "LIVE REVIEW ELIGIBLE · OPERATOR ONLY",
        "short_label": f"LIVE REVIEW {int(round(s))}",
        "color": "amber_high",
        "verdict": "READY_FOR_LIVE_REVIEW_OPERATOR_ONLY",
        "show_score": True,
    }


def liquidity_warnings(
    proposal: dict[str, Any],
    *,
    min_oi: int = DEFAULT_MIN_OI,
    min_volume: int = DEFAULT_MIN_VOLUME,
    max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT,
) -> list[dict[str, str]]:
    """Visible liquidity warnings for collapsed + expanded card."""
    warnings: list[dict[str, str]] = []
    oi = proposal.get("oi")
    vol = proposal.get("volume")
    spread = proposal.get("spread_pct")
    if oi is not None and int(oi) == 0:
        warnings.append({
            "code": "oi_zero",
            "severity": "danger",
            "message": "Illiquid contract — open interest is 0. Do not trade without live chain review.",
        })
    elif oi is not None and int(oi) < min_oi:
        warnings.append({
            "code": "low_oi",
            "severity": "warn",
            "message": f"Low open interest ({int(oi)} < {min_oi}).",
        })
    if vol is not None and int(vol) < min_volume:
        warnings.append({
            "code": "low_volume",
            "severity": "warn",
            "message": f"Low / no volume ({int(vol)} < {min_volume}).",
        })
    if spread is not None and float(spread) > max_spread_pct:
        warnings.append({
            "code": "wide_spread",
            "severity": "warn",
            "message": f"Wide spread ({float(spread):.1f}% > {max_spread_pct:.0f}%).",
        })
    return warnings


def sanitize_action_buttons(proposal: dict[str, Any]) -> list[dict[str, str]]:
    """Return safe action buttons for card rendering."""
    if is_card_blocked(proposal):
        review_label = (
            "Review Paper Guards" if is_paper_model_row(proposal) else "Review Block Reason"
        )
        buttons = [
            {"action": "review_chain", "label": "View Chain"},
            {"action": "review_block_reason", "label": review_label},
            {"action": "rerun_review", "label": "Rerun Review"},
            {"action": "hold", "label": "Pass"},
        ]
        return buttons
    raw = list(proposal.get("action_buttons") or [])
    out = [b for b in raw if str(b.get("action") or "") not in EXEC_TRADE_ACTIONS or not is_card_blocked(proposal)]
    if not out:
        out = [
            {"action": "review_chain", "label": "View Chain"},
            {"action": "hold", "label": "Pass"},
        ]
    return out


def plain_english_strategy_hint(strategy: str) -> str:
    s = (strategy or "").lower()
    if s == "deep_itm_call":
        return (
            "Paper model: this simulates a deep-ITM call as stock replacement. "
            "You pay a debit, max loss is the premium paid, and no live order is placed. "
            "Use Alpaca Paper only after review."
        )
    if s == "protective_put":
        return (
            "Protective put: you pay a debit for downside hedge protection. "
            "Max loss on the option is premium paid; the hedge may offset losses in the underlying."
        )
    if s == "covered_call":
        return "You collect a credit, but upside is capped and shares may be assigned."
    if s == "cash_secured_put":
        return "You collect a credit, but may be assigned shares and must have cash reserved."
    if s in ("atm_call", "atm_put", "long_call"):
        return "You pay a debit for directional exposure. Max loss is premium paid unless hedged."
    if s in ("debit_spread", "earnings_put_debit_spread"):
        return "Net debit spread — you pay premium; max loss is capped at the debit paid."
    if s in ("credit_spread", "put_credit_spread", "call_credit_spread"):
        return "Net credit spread — you collect premium; max loss is defined by the long leg."
    return "Review the metrics and chain before trading."


def apply_card_semantics(proposal: dict[str, Any], *, schwab_armed: Optional[bool] = None) -> dict[str, Any]:
    """Enrich proposal dict with presentation-only semantics fields."""
    out = dict(proposal)
    strat = str(out.get("strategy") or "")
    side = out.get("side")
    cf_label = option_cashflow_label(strat, side=side, option_type=out.get("option_type"))
    out["cashflow_label"] = cf_label
    out["cashflow_is_credit"] = cashflow_is_credit(strat, side=side)
    route = execution_route_badge(out)
    out["execution_route_badge"] = route["label"]
    out["execution_route_kind"] = route["kind"]
    out["execution_note"] = execution_route_note(out, schwab_armed=schwab_armed)
    out["data_source_badge"] = (
        "Schwab chain" if out.get("data_source") == "schwab_chain"
        else "BS estimate" if out.get("data_source") == "bs_estimate"
        else None
    )
    out["is_paper_model_row"] = is_paper_model_row(out)
    out["card_blocked"] = is_card_blocked(out)
    out["desk_trade_blocked"] = is_desk_trade_blocked(out)
    out["safety_status_badge"] = safety_status_badge(out)
    out["action_buttons"] = sanitize_action_buttons(out)
    out["plain_english_hint"] = plain_english_strategy_hint(strat)
    liq = liquidity_warnings(out)
    out["liquidity_warnings"] = liq
    if any(w["code"] == "oi_zero" for w in liq):
        out["liquidity_status"] = "illiquid"
        if out.get("edge_score") is not None:
            out["display_edge_score"] = min(float(out["edge_score"]), OI_ZERO_SCORE_CAP)
        else:
            out["display_edge_score"] = OI_ZERO_SCORE_CAP
    else:
        out["liquidity_status"] = "ok" if not liq else "caution"
        out["display_edge_score"] = out.get("edge_score")
    pj = out.get("prime_json") or {}
    if isinstance(pj, dict) and pj.get("prime_score") is not None:
        out["prime_display"] = prime_display_label(pj.get("prime_score"), pj.get("verdict"))
    elif out.get("prime_score") is not None:
        out["prime_display"] = prime_display_label(out.get("prime_score"), out.get("prime_verdict"))
    if out.get("educational_paper_model"):
        ent = dict(out.get("enterprise") or {})
        ent["live_eligible"] = False
        out["enterprise"] = ent
    return out


def apply_card_semantics_batch(
    proposals: list[dict[str, Any]],
    *,
    schwab_armed: Optional[bool] = None,
) -> list[dict[str, Any]]:
    return [apply_card_semantics(p, schwab_armed=schwab_armed) for p in proposals]