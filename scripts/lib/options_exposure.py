"""Per-leg liquidity and combined same-symbol exposure for option proposals (Wave B, 2026-09-27).

Why: the desk showed the DELL $490 cash-secured put and the DELL $522.5/$497.5 put credit
spread as two separate ideas. Both lose when DELL falls, so taking both roughly doubles the
DELL bet -- the cards never said so, nor what the pair commits against cash and the shares
already held. Spreads also showed one liquidity line for a two-leg order.

What: deterministic arithmetic only -- per-leg bid/ask/OI/volume, and for every symbol with
two or more ideas the combined capital committed, combined expiration P/L at a few prices,
and a comparison with the account cash and the shares held. READ_ONLY_ADVISORY;
MBI_BEHAVIOR=0 (nothing here sizes or orders).
"""
from __future__ import annotations

from typing import Any, Optional

try:
    from lib.options_economics import _payoff
except ImportError:  # pragma: no cover
    from scripts.lib.options_economics import _payoff  # type: ignore

# Direction of the bet each structure expresses on the underlying.
DIRECTION = {
    "cash_secured_put": "bullish",
    "credit_spread": "bullish",   # the desk's spreads are bull put spreads
    "long_call": "bullish",
    "covered_call": "neutral_capped",
    "protective_put": "hedge",
    "long_put": "bearish",
}
SCENARIO_MOVES = (-0.30, -0.20, -0.10, 0.0, 0.10)


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def leg_liquidity(contract: Optional[dict[str, Any]], *, role: str, strike: Any) -> dict[str, Any]:
    """One leg's quote as the desk saw it. Missing fields stay None -- never a guess."""
    c = contract or {}
    bid, ask = _f(c.get("bid")), _f(c.get("ask"))
    mid = _f(c.get("mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2
    spread_pct = None
    if bid is not None and ask is not None and mid:
        spread_pct = round(100.0 * (ask - bid) / mid, 1)
    return {"role": role, "strike": _f(strike), "bid": bid, "ask": ask,
            "mid": round(mid, 2) if mid is not None else None,
            "open_interest": c.get("oi", c.get("open_interest")),
            "volume": c.get("volume", c.get("vol")),
            "spread_pct": spread_pct}


def _committed(p: dict[str, Any]) -> float:
    e = p.get("economics") or {}
    return float(e.get("cash_committed") or e.get("collateral") or e.get("option_cost_total") or 0.0)


def combined_exposure(proposals: list[dict[str, Any]], *, cash_by_account: Optional[dict[str, float]] = None,
                      shares_by_symbol: Optional[dict[str, float]] = None) -> dict[str, dict[str, Any]]:
    """symbol -> combined block, for symbols with two or more ideas on the desk."""
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for p in proposals:
        sym = str(p.get("symbol") or "").upper()
        if sym:
            by_sym.setdefault(sym, []).append(p)
    out: dict[str, dict[str, Any]] = {}
    for sym, ps in by_sym.items():
        if len(ps) < 2:
            continue
        spot = next((_f(p.get("underlying_price")) for p in ps if _f(p.get("underlying_price"))), None)
        dirs = sorted({DIRECTION.get(str(p.get("strategy") or ""), "other") for p in ps})
        committed = round(sum(_committed(p) for p in ps), 2)
        scen = []
        if spot:
            for mv in SCENARIO_MOVES:
                px = spot * (1 + mv)
                total, ok = 0.0, True
                for p in ps:
                    pay = _payoff(p)
                    if pay is None:
                        ok = False
                        break
                    total += pay(px) * 100 * int(_f(p.get("contracts")) or 1)
                scen.append({"move_pct": round(mv * 100), "price": round(px, 2),
                             "combined_pl_at_expiry": round(total, 2) if ok else None})
        accts = sorted({str(p.get("account") or "") for p in ps if p.get("account")})
        cash = None
        if cash_by_account is not None and accts:
            cash = round(sum(float(cash_by_account.get(a) or 0.0) for a in accts), 2)
        same_way = len(dirs) == 1 and dirs[0] == "bullish"
        out[sym] = {
            "schema": "OptionsCombinedExposure@v1",
            "symbol": sym,
            "ideas": [{"id": p.get("id"), "strategy": p.get("strategy"),
                       "strike": p.get("strike"), "expiration": p.get("expiration")} for p in ps],
            "directions": dirs,
            "correlated": same_way,
            "capital_committed_total": committed,
            "accounts": accts,
            "account_cash": cash,
            "committed_pct_of_cash": (round(100.0 * committed / cash, 1) if cash else None),
            "shares_held": (shares_by_symbol or {}).get(sym),
            "scenarios": scen,
            "note": (f"These {len(ps)} {sym} ideas are the same bet (all lose if {sym} falls); taken "
                     f"together they commit ${committed:,.0f}. Compare with the scenario rows, not "
                     f"each card alone." if same_way else
                     f"{len(ps)} {sym} ideas with different directions ({', '.join(dirs)}); read the "
                     f"combined scenario rows before taking more than one."),
            "authority": "READ_ONLY_ADVISORY",
        }
    return out
