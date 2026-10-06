"""Deterministic Options Desk preparation, shared by UI/API and final authorization.

No IO or authority here. The queue, thesis, model, authorization and broker writers
remain the existing owners. Adapter receipts must supply their own provider times.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

STRATEGIES = frozenset({"covered_call", "cash_secured_put", "protective_put", "long_call",
                        "long_put", "credit_spread", "debit_spread", "collar"})
GREEKS = ("delta", "gamma", "theta", "vega", "rho")
QUOTE_MAX_AGE_SECONDS = 3.0  # operator requirement, measured from provider bid/ask time
TIME_IN_FORCE = ("DAY", "GTC")


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def quantity(value) -> int:
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d <= 0 or d != d.to_integral_value():
            raise ValueError("Number of contracts/spreads must be a positive integer")
        return int(d)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ValueError("Number of contracts/spreads must be a positive integer") from None


def timestamp(value):
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (float, int)) and not isinstance(value, bool):
            dt = datetime.fromtimestamp(value / (1000 if value > 1e11 else 1), timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    default=str, allow_nan=False).encode()).hexdigest()


def refusal(code, reason, **details):
    return {"code": code, "reason": reason, **details}


def proposal_legs(p: dict, count=None) -> list[dict]:
    n = quantity(p.get("contracts", 1) if count is None else count)
    strategy = p.get("strategy")
    if strategy not in STRATEGIES:
        raise ValueError("Unsupported options strategy")
    side = "call" if strategy in {"covered_call", "long_call"} else "put"
    if strategy in {"credit_spread", "debit_spread"}:
        side = p.get("option_type") or "put"
        templates = [("SELL", side, p.get("short_strike")), ("BUY", side, p.get("long_strike"))]
    elif strategy == "collar":
        templates = [("BUY", "put", p.get("put_strike")), ("SELL", "call", p.get("call_strike"))]
    else:
        templates = [("SELL" if strategy in {"covered_call", "cash_secured_put"} else "BUY", side, p.get("strike"))]
    explicit = p.get("legs") or []
    if explicit and len(explicit) != len(templates):
        raise ValueError("Leg count differs from this strategy")
    legs = []
    for index, (action, right, strike) in enumerate(templates):
        source = explicit[index] if index < len(explicit) else {}
        if source:
            right = source.get("option_type") or right
            strike = source.get("strike", strike)
            action = {"long": "BUY", "short": "SELL", "BUY_TO_OPEN": "BUY", "SELL_TO_OPEN": "SELL"}.get(
                source.get("side"), source.get("side") or action)
        if right not in {"call", "put"} or action not in {"BUY", "SELL"} or not number(strike) or number(strike) <= 0:
            raise ValueError("Every leg requires a valid side, option type and strike")
        expiration = str(source.get("expiration") or source.get("exp") or p.get("expiration") or "")[:10]
        datetime.strptime(expiration, "%Y-%m-%d")
        ratio = quantity(source.get("ratio", 1))
        if ratio != 1:
            raise ValueError("Existing strategy permissions require one-to-one leg ratios")
        if action != templates[index][0] or right != templates[index][1]:
            raise ValueError("Leg side or option type differs from this strategy")
        legs.append({**source, "symbol": str(p.get("symbol") or p.get("underlying") or "").upper(),
                     "expiration": expiration, "option_type": right, "strike": number(strike),
                     "side": action, "ratio": ratio, "quantity": n * ratio})
    if len({l["expiration"] for l in legs}) != 1:
        raise ValueError("This desk requires a common expiration for all strategy legs")
    return legs


def quote_refusals(legs: list[dict], *, now: datetime) -> list[dict]:
    problems = []
    if not legs:
        return [refusal("quotes_missing", "No exact-contract quotes received")]
    for i, q in enumerate(legs):
        # Trade and OI publication times are intentionally never freshness fallbacks.
        qt = timestamp(q.get("quote_time"))
        if qt is None:
            problems.append(refusal("quote_timestamp_missing", "Provider bid/ask timestamp missing", leg=i))
        else:
            age = (now - qt).total_seconds()
            if age < 0 or age > QUOTE_MAX_AGE_SECONDS:
                problems.append(refusal("quote_future" if age < 0 else "quote_stale",
                    "Executable bid/ask must be between zero and three seconds old", leg=i, age_seconds=age))
        bid, ask = number(q.get("bid")), number(q.get("ask"))
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            problems.append(refusal("quote_invalid", "A positive, uncrossed, two-sided quote is required", leg=i))
        volume = number(q.get("volume"))
        if volume is None or volume < 0 or not volume.is_integer():
            problems.append(refusal("volume_invalid", "Contract volume is missing or invalid", leg=i))
        mult = number(q.get("multiplier"))
        if mult is None or mult <= 0:
            problems.append(refusal("multiplier_unknown", "Contract multiplier unavailable", leg=i))
        if q.get("nonstandard") or q.get("non_standard"):
            problems.append(refusal("deliverable_unsupported", "Adjusted deliverable requires separate review", leg=i))
    return problems


def order_binding(p: dict) -> dict:
    legs = proposal_legs(p)
    return {"symbol": p.get("symbol"), "strategy": p.get("strategy"), "account": p.get("account"),
            "contracts": quantity(p.get("contracts", 1)), "limit": str(Decimal(str(p.get("premium")))),
            "tif": p.get("tif", "DAY"), "directive_id": p.get("directive_id"),
            "directive_version": p.get("directive_version"),
            "thesis_pin": (p.get("options_thesis") or {}).get("pin"),
            "symbol_thesis_pin": p.get("thesis_version_at_decision"),
            "legs": [{k: l.get(k) for k in ("symbol", "expiration", "option_type", "strike", "side", "ratio",
                                            "quantity", "multiplier", "deliverables", "occ_symbol")} for l in legs]}


def revision(p: dict) -> str:
    return digest({"order": order_binding(p), "economics": p.get("workflow_economics"), "lane": p.get("analysis_lane"), "generation": p.get("revision_generation")})


def analysis_binding(p: dict) -> str:
    return digest({"order": order_binding(p), "economics": p.get("workflow_economics"),
                   "lane": p.get("analysis_lane")})


def analysis_refusals(p, result, *, now, max_age_seconds=86400):
    result = result or {}
    binding = analysis_binding(p)
    if result.get("status") != "completed" or not result.get("id"):
        return [refusal("analysis_required", "A completed analysis from the selected lane is required",
                        status=result.get("status") or "missing", detail=result.get("error"))]
    if result.get("lane") != p.get("analysis_lane") or result.get("binding") != binding:
        return [refusal("analysis_changed", "Analysis does not cover this lane, thesis and reviewed economics")]
    at = timestamp(result.get("created_at"))
    if at is None or not 0 <= (now - at).total_seconds() <= max_age_seconds:
        return [refusal("analysis_stale", "Analysis is missing a valid timestamp or has expired")]
    if result.get("objections"):
        disposition = p.get("analysis_disposition") or {}
        if (disposition.get("analysis_id") != result["id"] or disposition.get("binding") != binding
                or not disposition.get("cio_decision_ref") or not str(disposition.get("note") or "").strip()):
            return [refusal("analysis_objections_unresolved", "Model objections require a recorded CIO disposition")]
    return []


def stamp_economics(p: dict) -> dict:
    """Keep legacy desk risk readers on the same deterministic reviewed totals."""
    e = economics(p)
    p["workflow_economics"] = e
    p.update(premium_total=e["premium_total"], max_profit=e["max_profit"], max_loss=e["max_loss"],
             breakeven=e["breakevens"][0] if len(e["breakevens"]) == 1 else None,
             risk_reward=e["max_profit"] / e["max_loss"] if e["max_profit"] is not None and e["max_loss"] else None,
             multiplier=proposal_legs(p)[0]["multiplier"])
    p["economics"] = {**(p.get("economics") or {}), "premium_total": e["premium_total"],
        "cash_committed": e["capital_required"], "collateral": e["capital_required"],
        "option_cost_total": e["premium_total"] if e["cash_flow"] == "debit" else None,
        "fees_total": e["fees_total"], "max_profit": e["max_profit"], "max_loss": e["max_loss"],
        "break_even": p["breakeven"]}
    return e


def economics(p: dict) -> dict:
    """Exact piecewise-linear expiration payoff. Unknown fees/Greeks stay unknown.

    Scenario prices are deterministic illustrations, not forecasts. Probability is
    only supplied by the existing payoff model with its explicit assumptions.
    """
    n = quantity(p.get("contracts", 1))
    legs = proposal_legs(p)
    mults = [number(l.get("multiplier")) for l in legs]
    if any(m is None or m <= 0 for m in mults) or len(set(mults)) != 1:
        raise ValueError("Known, consistent contract multipliers are required")
    if any(l.get("nonstandard") or l.get("non_standard") for l in legs):
        raise ValueError("Adjusted deliverable economics are unavailable")
    m = mults[0]
    price, spot = number(p.get("premium")), number(p.get("underlying_price"))
    if price is None or price < 0 or spot is None or spot <= 0:
        raise ValueError("Finite limit price and timestamped underlying price required")
    credit = p["strategy"] in {"covered_call", "cash_secured_put", "credit_spread"}
    signed = price if credit else -price
    if p["strategy"] == "collar":
        signed = -float(p.get("net_debit", price))
    premium_total = price * m * n
    fees = number(p.get("fees_total"))
    basis_quantity = number(p.get("fees_basis_contracts"))
    if fees is not None and basis_quantity is not None and basis_quantity > 0:
        fees = fees * n / basis_quantity
    if fees is not None and fees < 0:
        raise ValueError("Fees cannot be negative")
    cost = fees or 0
    stock = p["strategy"] in {"covered_call", "protective_put", "collar"}
    covered = max(l["quantity"] * m for l in legs) if stock else 0

    def option_payoff(s):
        result = signed * m * n - cost
        for l in legs:
            intrinsic = max(s - l["strike"], 0) if l["option_type"] == "call" else max(l["strike"] - s, 0)
            result += (1 if l["side"] == "BUY" else -1) * intrinsic * m * l["quantity"]
        return result

    def package(s):
        return option_payoff(s) + ((s - spot) * covered if stock else 0)

    knots = sorted({0.0, *(l["strike"] for l in legs)})
    values = [package(s) for s in knots]
    slope = package(knots[-1] + 1) - package(knots[-1])
    maximum = None if slope > 1e-8 else max(values)
    minimum = None if slope < -1e-8 else min(values)
    roots = []
    for a, b in zip(knots, [*knots[1:], math.inf]):
        step = 1 if math.isinf(b) else b - a
        rate = (package(a + step) - package(a)) / step
        if abs(rate) > 1e-9:
            root = a - package(a) / rate
            if a <= root <= b:
                roots.append(round(root, 6))
    greeks = {}
    for greek in GREEKS:
        known = [number(l.get(greek)) for l in legs]
        greeks[greek] = (sum(v * l["quantity"] * m * (1 if l["side"] == "BUY" else -1)
                             for v, l in zip(known, legs)) if all(v is not None for v in known) else None)
    cash = max(0, -signed * m * n) + cost
    if p["strategy"] == "cash_secured_put":
        cash = legs[0]["strike"] * m * n + cost
    elif p["strategy"] == "credit_spread":
        cash = abs(legs[0]["strike"] - legs[1]["strike"]) * m * n + cost
    target = number((p.get("directive") or {}).get("thesis_target"))
    scenario_prices = {spot * .8, spot, spot * 1.2, *roots, *(l["strike"] for l in legs)}
    custom = p.get("scenario_prices") or []
    if not isinstance(custom, list) or len(custom) > 40 or any(number(s) is None or number(s) < 0 for s in custom):
        raise ValueError("Use up to 40 nonnegative finite stock prices for scenarios")
    scenario_prices.update(float(s) for s in custom)
    if target is not None and target > 0:
        scenario_prices.update({target, (spot + target) / 2})
    return_capital = cash if cash > 0 else spot * m * n
    scenarios = [{"underlying_price": round(s, 4), "option_pl": round(option_payoff(s), 2),
                  "option_expiry_value": round(option_payoff(s) - signed * m * n + cost, 2),
                  "option_return_pct": round(100 * option_payoff(s) / return_capital, 2) if return_capital else None,
                  "return_basis": "reserved capital" if credit else "option premium and known fees",
                  "stock_return_pct": round(100 * (s / spot - 1), 2),
                  "label": "flat" if s == spot else "recorded target" if s == target else "break-even" if round(s, 6) in roots else "illustration",
                  "combined_pl": round(package(s), 2) if stock else None,
                  "moneyness": [{"option_type": l["option_type"], "strike": l["strike"],
                    "state": "ATM" if s == l["strike"] else "ITM" if (
                        s > l["strike"] if l["option_type"] == "call" else s < l["strike"]) else "OTM"}
                    for l in legs]} for s in sorted(scenario_prices)]
    ranked = sorted(scenarios, key=lambda r: r["combined_pl"] if stock else r["option_pl"])
    out = {"premium_total": round(premium_total, 2), "cash_flow": "credit" if signed >= 0 else "debit",
           "fees_total": fees, "fees_basis": "provided estimate" if fees is not None else "unknown; excluded",
           "capital_required": round(cash, 2), "shares_required": covered,
           "max_profit": round(maximum, 2) if maximum is not None else None,
           "max_loss": round(max(0, -minimum), 2) if minimum is not None else None,
           "profit_unlimited": maximum is None, "loss_unlimited": minimum is None,
           "breakevens": sorted(set(roots)), "greeks": greeks, "scenarios": scenarios,
           "best_scenario": ranked[-1], "worst_scenario": ranked[0],
           "base_scenario": next(r for r in scenarios if r["underlying_price"] == round(spot, 4)),
           "scenario_basis": "Illustrative expiry prices: spot -20%, unchanged, +20%, and strikes; not forecasts",
           "package_basis": "stock plus options from captured mark" if stock else "options only",
           "early_assignment_probability": None,
           "assignment_note": "Early-assignment probability unavailable. Review dividend dates, extrinsic value and expiry.",
           "probability_of_profit_pct": None, "probability_basis": "Model estimate unavailable"}
    out["expiry_date"] = legs[0]["expiration"]
    out["before_expiry_note"] = "You can sell before expiry. Sale value depends on the executable bid, remaining time, volatility, rates and dividends; these expiry outcomes are not before-expiry price forecasts."
    out["stock_comparison"] = {"equivalent_shares": m, "stock_cost": spot * m,
                               "option_cost": price * m, "target": target,
                               "target_stock_return_pct": (target / spot - 1) * 100 if target else None,
                               "target_option_pl_per_contract": option_payoff(target) / n if target else None,
                               "target_option_return_pct": option_payoff(target) / (price * m * n) * 100 if target and price else None}
    if len(legs) == 1:
        intrinsic = max(0, spot - legs[0]["strike"] if legs[0]["option_type"] == "call" else legs[0]["strike"] - spot)
        out["stock_comparison"].update(intrinsic_per_share=intrinsic, extrinsic_per_share=max(0, price - intrinsic),
                                      extrinsic_pct_of_stock=max(0, price - intrinsic) / spot * 100)
    if p["strategy"] == "long_call" and price < spot:
        out["stock_comparison"]["outperformance_stock_price_at_expiry"] = legs[0]["strike"] * spot / (spot - price)
    out["stock_comparison"]["breakeven_stock_change_pct"] = [(b / spot - 1) * 100 for b in roots]
    out["per_contract"] = {k: out[k] / n if out[k] is not None else None
                           for k in ("premium_total", "fees_total", "capital_required", "max_profit", "max_loss")}
    out["per_contract"]["greeks"] = {k: v / n if v is not None else None for k, v in greeks.items()}
    # Reuse the existing model only for its supported, equal-ratio payoff shapes.
    if all(l["ratio"] == 1 for l in legs):
        from scripts.lib.options_economics import payoff_metrics
        modeled = payoff_metrics({**p, "multiplier": m})
        out.update({k: modeled.get(k) for k in ("probability_of_profit_pct", "probability_basis")})
    return out
