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


def _iso(v: Any) -> Optional[str]:
    """Epoch ms/s or ISO string -> ISO 8601 UTC; None when absent."""
    if v in (None, "", 0):
        return None
    try:
        from datetime import datetime, timezone
        if isinstance(v, (int, float)):
            ts = float(v) / (1000.0 if float(v) > 1e11 else 1.0)
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        return str(v)
    except (TypeError, ValueError, OSError):
        return None


def leg_quote(contract: Optional[dict[str, Any]], *, role: str) -> dict[str, Any]:
    """One leg's quote with its timestamp, as the desk saw it. Never a guess."""
    c = contract or {}
    bid, ask, last = _f(c.get("bid")), _f(c.get("ask")), _f(c.get("last"))
    mid = _f(c.get("mid"))
    if mid is None and bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2
    return {"role": role, "strike": _f(c.get("strike")), "expiration": c.get("exp") or c.get("expiration"),
            "bid": bid, "ask": ask, "mid": round(mid, 2) if mid is not None else None, "last": last,
            "mark": _f(c.get("mark")), "open_interest": c.get("oi", c.get("open_interest")),
            "volume": c.get("volume", c.get("vol")), "quote_time": _iso(c.get("quote_time")),
            "two_sided": bool(bid and ask and bid > 0 and ask > bid)}


def spread_quote(short_c: dict[str, Any], long_c: dict[str, Any], *, session: Optional[str] = None,
                 quotes_as_of: Optional[str] = None) -> dict[str, Any]:
    """Credit of a two-leg credit spread under an EXPLICIT fill assumption (operator 2026-09-27).

    The desk advertised the leg-midpoint difference as the credit: DELL $8.10 while selling the
    short put at its bid and buying the long put at its ask gave $6.35; ETON $0.89 while crossing
    the displayed quotes was a $2.00 DEBIT. A midpoint is not a fill. ``executable_credit`` is
    short bid minus long ask -- the credit a marketable limit at the displayed quotes would
    receive -- and is what the payoff is priced from. The midpoint is kept, labelled, for
    comparison. Deterministic arithmetic only; READ_ONLY_ADVISORY."""
    sq, lq = leg_quote(short_c, role="short put"), leg_quote(long_c, role="long put")
    mid_credit = (round(sq["mid"] - lq["mid"], 2) if sq["mid"] is not None and lq["mid"] is not None else None)
    exec_credit = None
    if sq["bid"] is not None and lq["ask"] is not None and sq["two_sided"] and lq["two_sided"]:
        exec_credit = round(sq["bid"] - lq["ask"], 2)
    basis = "executable" if exec_credit is not None else ("midpoint" if mid_credit is not None else None)
    return {
        "schema": "OptionsSpreadQuote@v1",
        "mid_credit": mid_credit,
        "executable_credit": exec_credit,
        "credit_basis": basis,
        "credit_haircut": (round(mid_credit - exec_credit, 2)
                           if mid_credit is not None and exec_credit is not None else None),
        "fill_assumption": ("sell the short leg at its bid, buy the long leg at its ask (marketable limit "
                            "at the displayed quotes)" if exec_credit is not None else
                            "leg midpoints only: one leg has no two-sided quote"),
        "legs": [sq, lq],
        "quotes_as_of": quotes_as_of or sq["quote_time"] or lq["quote_time"],
        "market_session": session,
        "is_credit": (exec_credit is not None and exec_credit > 0),
    }


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
        credit = _f(p.get("executable_credit"))
        if credit is None:
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


def economics(p: dict[str, Any], *, shares_held: Optional[float] = None,
              quote_issues: Optional[list[str]] = None, session: Optional[str] = None) -> dict[str, Any]:
    """Economics block for one proposal. Missing inputs give None, never a guess.

    ``quote_issues`` (the liquidity gate's failures) withholds expected P/L: on a 185%-wide
    weekend quote the desk's IV is not the market's, and XLB's hedge showed +$827 on a
    $345 put (Wave B, 2026-09-27). Strike/premium arithmetic is still shown, at the mid."""
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
    if ev is not None:
        # A bare figure is not a fact (operator 2026-09-27): say what it was computed from.
        basis = p.get("credit_basis") or ("executable" if p.get("executable_credit") is not None else "midpoint")
        credit_in = (_f(p.get("executable_credit")) if strat == "credit_spread" and p.get("executable_credit") is not None
                     else (_f(p.get("net_credit")) if strat == "credit_spread" else prem))
        out["ev_inputs"] = {"credit_or_premium": credit_in, "credit_basis": basis if strat == "credit_spread" else "quote mid",
                            "iv": iv, "spot": spot, "dte": dte, "quotes_as_of": p.get("quotes_as_of"),
                            "market_session": session}
        caveats = []
        if session and session != "REGULAR":
            caveats.append(f"closed-market quote ({str(session).lower().replace('_', ' ')})")
        if strat == "credit_spread" and basis == "midpoint":
            caveats.append("credit is a leg midpoint, not a fill")
        out["ev_caveat"] = ("model estimate at the desk's IV" + (" on a " + "; ".join(caveats) if caveats else "")
                            + "; recheck on live validated quotes before acting")
    if quote_issues:
        out["expected_pl_at_expiry"] = None
        out["expected_pl_status"] = "withheld: quotes not tradeable (" + "; ".join(map(str, quote_issues[:3])) + ")"
        out["prices_basis"] = "mid of a non-tradeable quote; recheck on live quotes"
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
        exec_credit = _f(p.get("executable_credit"))
        credit = exec_credit if exec_credit is not None else (_f(p.get("net_credit")) or prem)
        if sk is not None and lk is not None and credit is not None:
            out.update({"credit_total": round(credit * mult, 2),
                        "collateral": round((sk - lk) * mult, 2),
                        "max_loss_total": round((sk - lk - credit) * mult, 2),
                        "breakeven": round(sk - credit, 2),
                        "credit_basis": "executable" if exec_credit is not None else "midpoint"})
            mid_credit = _f(p.get("mid_credit"))
            if exec_credit is not None and mid_credit is not None:
                out.update({"credit_total_at_mid": round(mid_credit * mult, 2),
                            "max_loss_total_at_mid": round((sk - lk - mid_credit) * mult, 2),
                            "breakeven_at_mid": round(sk - mid_credit, 2),
                            "credit_haircut_total": round((mid_credit - exec_credit) * mult, 2),
                            "prices_basis": "sell short leg at bid, buy long leg at ask; midpoint shown for comparison"})
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
            # Operator 2026-09-27: the card is insurance for held stock, so the headline max loss
            # is the hedged shares' loss to the floor from the mark (premium included), and the
            # put-alone figures are labelled as such rather than shown as "max loss"/"breakeven".
            "hedged_max_loss_from_mark": round(max(0.0, spot - (k - prem)) * insured, 2),
            "option_max_loss": round(prem * mult, 2),
            "put_breakeven": round(k - prem, 2),
            "uninsured_downside_note": (None if shares_held is None or shares_held - insured <= 0 else
                                        f"{round(shares_held - insured, 3):g} shares beyond the {insured} insured "
                                        f"are unhedged and fall with the stock"),
            "note": "Max loss of the hedged shares is to the floor, not the premium; P/L vs your "
                    "actual cost basis differs from the mark.",
        })
    return out
