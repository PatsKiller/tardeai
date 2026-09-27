"""Honest per-strategy economics for option proposals (operator 2026-09-27).

Why: the desk's "expected value" was `credit x POP` for every income trade -- it
counted the chance of keeping the credit and ignored the losses (DELL $490 put:
"EV $1,473" = 68.3% x $2,157). Protective puts used a placeholder `-cost x 0.5`.

What: expected P/L at expiration, integrated over a lognormal price distribution
with the SAME volatility the desk used for POP and zero drift. For a fairly priced
option that is close to zero by construction -- which is the point: POP alone makes
selling premium look like free money. Plus the figures an operator asks for:
net cost of stock if assigned (strike - premium), cash committed, insured and
uninsured shares, and the stock-plus-put floor. Deterministic arithmetic only;
READ_ONLY_ADVISORY; MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

GRID = 400  # integration points over +/- 6 standard deviations


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def expected_payoff(payoff: Callable[[float], float], spot: float, iv: float, dte: int) -> Optional[float]:
    """E[payoff(S_T)] with ln S_T ~ N(ln S - sigma^2 T / 2, sigma^2 T) (zero drift)."""
    if not spot or spot <= 0 or not iv or iv <= 0 or dte is None:
        return None
    t = max(int(dte), 1) / 365.0
    s = iv * math.sqrt(t)
    mu = math.log(spot) - 0.5 * s * s
    lo, hi = mu - 6 * s, mu + 6 * s
    step = (hi - lo) / GRID
    total = 0.0
    for i in range(GRID):
        x = lo + (i + 0.5) * step
        w = math.exp(-0.5 * ((x - mu) / s) ** 2) / (s * math.sqrt(2 * math.pi)) * step
        total += w * payoff(math.exp(x))
    return total


def _payoff(p: dict[str, Any]) -> Optional[Callable[[float], float]]:
    """Per-share expiration P/L of the OPTION position (not the stock) as a function of S_T."""
    strat = str(p.get("strategy") or "")
    k = _f(p.get("strike"))
    prem = _f(p.get("premium"))
    if strat == "credit_spread":
        short_k = _f(p.get("short_strike")) or k
        long_k = _f(p.get("long_strike"))
        credit = _f(p.get("net_credit")) or prem
        if short_k is None or long_k is None or credit is None:
            return None
        return lambda s: credit - max(short_k - s, 0.0) + max(long_k - s, 0.0)
    if k is None or prem is None:
        return None
    if strat == "cash_secured_put":
        return lambda s: prem - max(k - s, 0.0)
    if strat == "covered_call":
        return lambda s: prem - max(s - k, 0.0)
    if strat in ("protective_put", "long_put"):
        return lambda s: max(k - s, 0.0) - prem
    if strat == "long_call":
        return lambda s: max(s - k, 0.0) - prem
    return None


def economics(p: dict[str, Any], *, shares_held: Optional[float] = None) -> dict[str, Any]:
    """Economics block for one proposal. Missing inputs give None, never a guess."""
    strat = str(p.get("strategy") or "")
    n = int(_f(p.get("contracts")) or 1)
    mult = 100 * n
    spot = _f(p.get("underlying_price"))
    iv = _f(p.get("iv_used"))
    dte = p.get("dte")
    k = _f(p.get("strike"))
    prem = _f(p.get("premium"))
    out: dict[str, Any] = {"schema": "OptionsEconomics@v1", "contracts": n, "multiplier": 100,
                           "ev_method": "expected P/L at expiration, lognormal at the desk's IV, zero drift"}
    pay = _payoff(p)
    ev = expected_payoff(pay, spot, iv, dte) if pay else None
    out["expected_pl_at_expiry"] = round(ev * mult, 2) if ev is not None else None
    if strat == "cash_secured_put" and k is not None and prem is not None:
        out.update({
            "net_cost_if_assigned_per_share": round(k - prem, 2),
            "net_cost_if_assigned_total": round((k - prem) * mult, 2),
            "cash_committed": round(k * mult, 2),
            "discount_to_spot_pct": round(100.0 * (1 - (k - prem) / spot), 1) if spot else None,
            "credit_total": round(prem * mult, 2),
        })
    if strat == "covered_call" and k is not None and prem is not None:
        out.update({
            "credit_total": round(prem * mult, 2),
            "called_away_price_per_share": round(k + prem, 2),
            "shares_committed": mult,
        })
    if strat == "credit_spread":
        sk, lk = _f(p.get("short_strike")) or k, _f(p.get("long_strike"))
        credit = _f(p.get("net_credit")) or prem
        if sk is not None and lk is not None and credit is not None:
            out.update({"credit_total": round(credit * mult, 2),
                        "collateral": round((sk - lk) * mult, 2),
                        "max_loss_total": round((sk - lk - credit) * mult, 2),
                        "breakeven": round(sk - credit, 2)})
    if strat == "protective_put" and k is not None and prem is not None and spot:
        insured = mult
        out.update({
            "option_cost_total": round(prem * mult, 2),
            "insured_shares": insured,
            "uninsured_shares": (round(max(0.0, shares_held - insured), 3) if shares_held is not None else None),
            "floor_value_after_premium": round((k - prem) * insured, 2),
            "position_value_at_mark": round(spot * insured, 2),
            "downside_to_floor_from_mark": round((spot - (k - prem)) * insured, 2),
            "stock_plus_put_breakeven_from_mark": round(spot + prem, 2),
            "note": "Max loss of the hedged shares is to the floor, not the premium; P/L vs your "
                    "actual cost basis differs from the mark.",
        })
    return out
