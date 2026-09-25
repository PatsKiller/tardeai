"""Canonical stock-versus-options comparison for one recommendation.

Pure. No network. Matches OPTIONS_DESK_RECOMMENDATION_SPEC_2026-09-25.
Missing numbers stay null. A blocked, stale, or modeled option cannot be
the preferred structure. Ensemble output is not a CIO disposition.

READ_ONLY_ADVISORY. This object has no shares, qty, order, or size_usd field.
"""
from __future__ import annotations

from typing import Any, Optional

POLICY_VERSION = "AGENTS.md 1.2.7 PROPOSED"
AUTHORITY = "READ_ONLY_ADVISORY"
_BEHAVIOR_KEYS = frozenset({"shares", "qty", "order", "size_usd"})
_DISPOSITIONS = frozenset({"reviewed", "challenged", "deferred"})


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _blocks(proposal: dict[str, Any]) -> list[str]:
    raw = (proposal.get("enterprise") or {}).get("blocks") or proposal.get("blocks") or []
    out = []
    for item in raw:
        if isinstance(item, dict):
            out.append(str(item.get("reason") or item.get("code") or ""))
        else:
            out.append(str(item))
    return [x for x in out if x]


def _freshness(proposal: dict[str, Any]) -> str:
    if proposal.get("quote_stale") or proposal.get("stale"):
        return "stale"
    blob = " ".join(_blocks(proposal)).lower()
    if "stale" in blob:
        return "stale"
    src = str(proposal.get("data_source") or "").lower()
    if proposal.get("educational_paper_model") or proposal.get("paper_only") or src == "bs_estimate":
        return "modeled"
    if "bs estimate" in blob or "black-scholes" in blob or "paper model" in blob:
        return "modeled"
    if src == "schwab_chain":
        return "live_chain"
    if not src:
        return "unavailable"
    return "unavailable"


def _liquidity(proposal: dict[str, Any], freshness: str) -> str:
    if freshness in {"stale", "modeled", "unavailable"}:
        return "block" if freshness != "unavailable" else "unavailable"
    blocks = _blocks(proposal)
    if blocks or proposal.get("enterprise_blocked") or (proposal.get("enterprise") or {}).get("live_eligible") is False:
        if blocks:
            return "block"
    liq = (proposal.get("enterprise") or {}).get("liquidity") or {}
    if liq.get("pass") is False:
        return "block"
    if liq.get("pass") is True:
        return "pass"
    return "unavailable"


def _is_vertical(strategy: str) -> bool:
    s = strategy.lower()
    return "spread" in s


def _package_max_loss(proposal: dict[str, Any]) -> float | None:
    for key in ("max_loss", "package_max_loss", "maximum_loss"):
        n = _f(proposal.get(key))
        if n is not None and n > 0:
            return n
    return None


def _pop(proposal: dict[str, Any]) -> tuple[float | None, str | None]:
    basis = proposal.get("pop_basis") or proposal.get("probability_basis")
    raw = proposal.get("pop_pct")
    if raw is None:
        raw = proposal.get("probability_of_profit")
    n = _f(raw)
    if n is None or not basis:
        return None, None
    return n, str(basis)


def build_recommendation_comparison(
    proposal: dict[str, Any],
    *,
    equity: Optional[dict[str, Any]] = None,
    thesis: Optional[dict[str, Any]] = None,
    generated_at: Optional[str] = None,
    cio_disposition: Optional[str] = None,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    """One comparison. Identical inputs return an identical object."""
    equity = equity or {}
    thesis = thesis or {}
    strategy = str(proposal.get("strategy") or "")
    symbol = str(proposal.get("symbol") or proposal.get("underlying") or "").upper()
    price = _f(equity.get("price") if equity.get("price") is not None else proposal.get("underlying_price"))
    stop = _f(equity.get("stop") if equity.get("stop") is not None else proposal.get("stop"))
    share_count = _f(equity.get("share_count") if equity.get("share_count") is not None else proposal.get("share_count"))
    pin = thesis.get("thesis_version")
    if not pin:
        try:
            from scripts.lib.cio_theses import safe_current_pin
            pin = safe_current_pin("desk")
        except Exception:
            try:
                from lib.cio_theses import safe_current_pin  # type: ignore
                pin = safe_current_pin("desk")
            except Exception:
                pin = None
    freshness = _freshness(proposal)
    liquidity = _liquidity(proposal, freshness)
    blocked = liquidity == "block" or bool(_blocks(proposal))
    horizon = proposal.get("time_horizon") or (f"{proposal.get('dte')} DTE" if proposal.get("dte") else None)
    pop, pop_basis = _pop(proposal)

    stock_capital = None
    stock_loss = None
    stock_model = "unavailable"
    stock_action = "unavailable"
    risk_notes: list[str] = []
    if strategy == "covered_call" and share_count is not None and share_count < 100:
        risk_notes.append("NEED_100_SHARES")
        stock_model = "Covered call needs 100 shares. Fewer shares is not a covered call."
    elif price is not None and share_count is not None and share_count > 0:
        stock_capital = round(price * share_count, 2)
        if stop is not None and price > stop:
            stock_loss = round((price - stop) * share_count, 2)
            stock_model = "Shares held to the stop. Premium is income, not the risk."
            stock_action = "hold" if strategy == "covered_call" else "buy"
        else:
            stock_model = "Price is present and the stop is missing, so share risk is unavailable."
    if str(thesis.get("verdict") or "").lower() == "avoid":
        stock_action = "avoid"

    option_capital = None
    option_risk = None
    option_profit = _f(proposal.get("max_profit") or proposal.get("expected_return"))
    expected_return = option_profit if proposal.get("expected_return_basis") else None
    if strategy == "covered_call":
        option_risk = stock_loss
        option_capital = _f(proposal.get("premium_total") or proposal.get("premium"))
        if option_risk is None:
            option_capital = None
    elif _is_vertical(strategy):
        option_risk = _package_max_loss(proposal)
        option_capital = option_risk
    else:
        option_risk = _f(proposal.get("max_loss") or proposal.get("premium_total"))
        option_capital = _f(proposal.get("premium_total") or proposal.get("capital_required"))

    disposition = str(cio_disposition or proposal.get("cio_disposition") or "").lower()
    review_status = disposition if disposition in _DISPOSITIONS else "unreviewed"
    commentary = proposal.get("eligibility_sentence") or proposal.get("cio_commentary")
    if commentary:
        commentary = f"Desk narrative, not a CIO disposition: {commentary}"
    else:
        commentary = "No CIO disposition is on file. Model or ensemble output is not a review."

    preferred = "review_required"
    capital_efficiency = None
    risk_reward = None
    if str(thesis.get("verdict") or "").lower() == "avoid":
        preferred = "neither"
    elif (
        not blocked
        and freshness == "live_chain"
        and pin
        and pop is not None
        and option_risk is not None
        and option_capital not in (None, 0)
        and stock_loss is not None
        and stock_capital not in (None, 0)
        and horizon
    ):
        option_ratio = option_risk / option_capital
        stock_ratio = stock_loss / stock_capital
        risk_reward = round(option_ratio, 4)
        if option_ratio < stock_ratio:
            preferred = "options"
            capital_efficiency = "Defined option loss per dollar of option capital is lower than share loss per dollar of stock capital, on the same horizon."
        else:
            preferred = "stock"
            capital_efficiency = "Share loss per dollar of stock capital is lower than the option, or the option does not improve the loss ratio."
    elif stock_action == "avoid":
        preferred = "neither"
    if "NEED_100_SHARES" in risk_notes or freshness != "live_chain":
        if preferred == "options":
            preferred = "review_required"
    if "NEED_100_SHARES" in risk_notes:
        preferred = "review_required"

    out = {
        "underlying": {
            "symbol": symbol or None,
            "security_guid": proposal.get("security_guid") or proposal.get("issuer_guid"),
            "as_of": generated_at,
        },
        "thesis": {
            "verdict": thesis.get("verdict"),
            "direction": thesis.get("direction"),
            "thesis_version": pin,
            "evidence_refs": list(thesis.get("evidence_refs") or []),
        },
        "stock_play": {
            "action": stock_action if pin else "unavailable",
            "capital_required": stock_capital if pin else None,
            "maximum_loss_model": stock_model,
            "expected_return": None,
            "time_horizon": horizon,
            "risk_notes": risk_notes,
        },
        "options_play": {
            "structure": strategy or None,
            "legs": list(proposal.get("legs") or []),
            "capital_required": option_capital,
            "maximum_risk": option_risk,
            "expected_return": expected_return,
            "expected_return_basis": proposal.get("expected_return_basis"),
            "probability_of_success": pop,
            "probability_basis": pop_basis,
            "probability_as_of": generated_at if pop is not None else None,
            "expiration_rationale": proposal.get("expiration_rationale"),
            "strike_rationale": proposal.get("strike_rationale"),
            "liquidity_status": liquidity,
        },
        "comparison": {
            "capital_efficiency": capital_efficiency,
            "risk_reward": risk_reward,
            "opportunity_cost": None,
            "cash_preservation": None,
            "concentration_effect": None,
            "preferred_structure": preferred,
        },
        "oversight": {
            "cio_commentary": commentary,
            "review_status": review_status,
            "authority": AUTHORITY,
        },
        "provenance": {
            "sources": [proposal.get("data_source") or "unavailable"],
            "generated_at": generated_at,
            "freshness": freshness,
            "model_or_engine": "recommendation_comparison",
            "policy_versions": [policy_version],
        },
    }
    if not pin:
        out["stock_play"]["action"] = "unavailable"
        out["comparison"]["preferred_structure"] = "review_required" if preferred != "neither" else "neither"
    _assert_no_behavior_keys(out)
    return out


def _assert_no_behavior_keys(node: Any) -> None:
    if isinstance(node, dict):
        bad = _BEHAVIOR_KEYS.intersection(node)
        if bad:
            raise ValueError(f"behavior keys in comparison: {sorted(bad)}")
        for v in node.values():
            _assert_no_behavior_keys(v)
    elif isinstance(node, list):
        for v in node:
            _assert_no_behavior_keys(v)
