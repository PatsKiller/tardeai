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
            "last": _f(c.get("last")), "mark": _f(c.get("mark")),
            "open_interest": c.get("oi", c.get("open_interest")),
            "volume": c.get("volume", c.get("vol")),
            "spread_pct": spread_pct,
            "quote_time": c.get("quote_time"),
            "two_sided": bool(bid and ask and bid > 0 and ask > bid)}


def _committed(p: dict[str, Any]) -> float:
    e = p.get("economics") or {}
    return float(e.get("cash_committed") or e.get("collateral") or e.get("option_cost_total") or 0.0)


def _shares_pl(shares: Optional[float], spot: float, px: float) -> Optional[float]:
    """Mark-to-mark change of the shares held at the scenario price (simplified: same price for
    every leg, no basis, no fees). None when the share count is unknown -- never zero by default."""
    return None if shares is None else round(shares * (px - spot), 2)


def _scenario_rows(ideas: list[dict[str, Any]], spot: float, shares: Optional[float]) -> list[dict[str, Any]]:
    rows = []
    for mv in SCENARIO_MOVES:
        px = spot * (1 + mv)
        total, ok = 0.0, True
        for p in ideas:
            pay = _payoff(p)
            if pay is None:
                ok = False
                break
            total += pay(px) * 100 * int(_f(p.get("contracts")) or 1)
        opt = round(total, 2) if ok else None
        sh = _shares_pl(shares, spot, px)
        rows.append({"move_pct": round(mv * 100), "price": round(px, 2),
                     "options_only_pl": opt, "shares_pl": sh,
                     "whole_position_pl": (round(opt + sh, 2) if opt is not None and sh is not None else None)})
    return rows


def combined_exposure(proposals: list[dict[str, Any]], *, cash_by_account: Optional[dict[str, float]] = None,
                      shares_by_symbol: Optional[dict[str, float]] = None,
                      shares_by_symbol_account: Optional[dict[str, dict[str, float]]] = None) -> dict[str, dict[str, Any]]:
    """symbol -> combined block, for symbols with two or more ideas on the desk.

    Reviewer 2026-09-28: the old block summed only the option payoffs, ignored the shares the
    reader holds (SPCX: +$8,951 at -30% on 400 held shares that would lose ~$17.6k) and labelled
    ideas with different expirations as one "at expiry" payoff. Now every scenario row carries
    options-only, shares and whole-position P/L separately, the rows are grouped by expiration
    date (a Nov-6 put and a Nov-20 spread cannot share one expiration payoff), and the shares are
    listed by account so the reader can see which shares a hedge covers."""
    by_sym: dict[str, list[dict[str, Any]]] = {}
    excluded: dict[str, list[dict[str, Any]]] = {}
    for p in proposals:
        sym = str(p.get("symbol") or "").upper()
        if not sym:
            continue
        # Operator 2026-09-27: an archived idea is not a live bet; it must not inflate the
        # combined exposure of the card that survived. Named, so the card can say what was left out.
        stage = str(((p.get("lifecycle") or {}).get("stage")) or "")
        if p.get("thesis_abandoned") or stage.startswith("ARCHIVED"):
            excluded.setdefault(sym, []).append({"id": p.get("id"), "strategy": p.get("strategy"),
                                                 "strike": p.get("strike"), "reason": "archived"})
            continue
        by_sym.setdefault(sym, []).append(p)
    out: dict[str, dict[str, Any]] = {}
    for sym, ps in by_sym.items():
        if len(ps) < 2:
            continue
        spot = next((_f(p.get("underlying_price")) for p in ps if _f(p.get("underlying_price"))), None)
        dirs = sorted({DIRECTION.get(str(p.get("strategy") or ""), "other") for p in ps})
        committed = round(sum(_committed(p) for p in ps), 2)
        shares = (shares_by_symbol or {}).get(sym)
        shares = _f(shares) if shares is not None else None
        by_acct = {str(a): round(float(n), 3) for a, n in ((shares_by_symbol_account or {}).get(sym) or {}).items() if _f(n)}
        expiries = sorted({str(p.get("expiration") or "") for p in ps})
        by_expiry: list[dict[str, Any]] = []
        if spot:
            for exp in expiries:
                ideas = [p for p in ps if str(p.get("expiration") or "") == exp]
                by_expiry.append({"expiration": exp or None,
                                  "ideas": [p.get("id") for p in ideas],
                                  "rows": _scenario_rows(ideas, spot, shares)})
        single_expiry = len(expiries) == 1
        accts = sorted({str(p.get("account") or "") for p in ps if p.get("account")})
        cash = None
        if cash_by_account is not None and accts:
            cash = round(sum(float(cash_by_account.get(a) or 0.0) for a in accts), 2)
        same_way = len(dirs) == 1 and dirs[0] == "bullish"
        out[sym] = {
            "schema": "OptionsCombinedExposure@v2",
            "symbol": sym,
            "ideas": [{"id": p.get("id"), "strategy": p.get("strategy"), "account": p.get("account"),
                       "strike": p.get("strike"), "expiration": p.get("expiration"),
                       "contracts": int(_f(p.get("contracts")) or 1)} for p in ps],
            "directions": dirs,
            "correlated": same_way,
            "capital_committed_total": committed,
            "accounts": accts,
            "account_cash": cash,
            "committed_pct_of_cash": (round(100.0 * committed / cash, 1) if cash else None),
            "spot": spot,
            "shares_held": shares,
            "shares_by_account": by_acct,
            "excluded_ideas": excluded.get(sym, []),
            # flat rows only when every idea expires the same day; otherwise read scenarios_by_expiry
            "scenarios": (by_expiry[0]["rows"] if single_expiry and by_expiry else []),
            "scenarios_by_expiry": by_expiry,
            "scenario_basis": ("Hypothetical if all shown ideas were selected, not existing commitments. "
                               "Options-only, shares and whole-position P/L at the same price on that expiration "
                               "date; shares are marked from today's spot, no basis or fees"
                               + ("" if shares is not None else "; shares held unknown, so whole-position P/L is withheld")),
            "expirations": [e or None for e in expiries],
            "note": (f"These {len(ps)} {sym} ideas are the same bet (all lose if {sym} falls); taken "
                     f"together they commit ${committed:,.0f}. Compare with the scenario rows, not "
                     f"each card alone." if same_way else
                     f"{len(ps)} {sym} ideas with {'the same direction' if len(dirs) == 1 else 'different directions'} ({', '.join(dirs)}); read the "
                     f"combined scenario rows before taking more than one.")
                    + ("" if single_expiry else f" The ideas expire on different dates ({', '.join(e for e in expiries if e)}); "
                       "each date has its own scenario table and no single at-expiry payoff exists."),
            "authority": "READ_ONLY_ADVISORY",
        }
    return out
