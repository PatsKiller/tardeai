"""Rank live option contracts against an operator's standing options intent. Pure functions.

Input is the compact chain shape schwab_transport.normalize_option_chain returns
({"underlying_price", "expirations": [{"exp", "strikes": [{side, strike, bid, ask, mark, iv,
delta, oi, volume, spread_pct, two_sided, dte, ...}]}]}). Nothing here calls a provider,
reads a database or writes anything. Advisory only (MBI_BEHAVIOR = 0).

Ported from the read-only OpenClaw tool (skills/tradeai-readonly/scripts/tradeai_options.py,
2026-10-05) so the Command Center and the agent rank contracts the same way.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_LIQUIDITY = {"max_spread_pct": 10.0, "min_oi": 50, "require_two_sided": True}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def contracts(chain: Dict[str, Any], side: str) -> List[Dict[str, Any]]:
    out = []
    for e in (chain or {}).get("expirations") or []:
        for s in e.get("strikes") or []:
            if s.get("side") == side:
                out.append(s)
    return out


def mid(c: Dict[str, Any]) -> Optional[float]:
    b, a = _f(c.get("bid")), _f(c.get("ask"))
    if b is not None and a is not None and a > 0:
        return (b + a) / 2.0
    return _f(c.get("mark")) or _f(c.get("last"))


def liquid(c: Dict[str, Any], liq: Optional[Dict[str, Any]] = None) -> bool:
    liq = {**DEFAULT_LIQUIDITY, **(liq or {})}
    if liq["require_two_sided"] and not c.get("two_sided"):
        return False
    sp = _f(c.get("spread_pct"))
    if sp is None or sp > float(liq["max_spread_pct"]):
        return False
    return (_f(c.get("oi")) or 0) >= float(liq["min_oi"])


def _in(v: Optional[float], rng: Optional[Iterable[float]]) -> bool:
    if rng is None:
        return True
    lo, hi = list(rng)[:2]
    return v is not None and float(lo) <= v <= float(hi)


def _crosses(exp: str, earnings_date: Optional[str]) -> Optional[bool]:
    if not earnings_date:
        return None
    return str(exp)[:10] >= str(earnings_date)[:10]


def _base(c: Dict[str, Any], m: float) -> Dict[str, Any]:
    return {"contract": c.get("symbol"), "exp": c.get("exp"), "strike": _f(c.get("strike")), "dte": c.get("dte"),
            "bid": c.get("bid"), "ask": c.get("ask"), "mid": round(m, 4), "iv": c.get("iv"), "delta": c.get("delta"),
            "oi": c.get("oi"), "volume": c.get("volume"), "spread_pct": c.get("spread_pct"),
            "quote_time": c.get("quote_time")}


def rank_csp(chain: Dict[str, Any], play: Dict[str, Any], *, earnings_date: Optional[str] = None,
             avoid_earnings_cross: bool = False, liq: Optional[Dict[str, Any]] = None,
             top: int = 5) -> List[Dict[str, Any]]:
    """Cash-secured puts: sell to open below spot; ranked by annualized return on cash."""
    spot = _f(chain.get("underlying_price"))
    if not spot:
        return []
    smax = _f(play.get("strike_max"))
    rows = []
    for c in contracts(chain, "put"):
        m, k = mid(c), _f(c.get("strike"))
        d = abs(_f(c.get("delta")) or 0)
        if not m or k is None or k >= spot or not liquid(c, liq):
            continue
        if not _in(c.get("dte"), play.get("dte")) or not _in(d, play.get("delta")):
            continue
        if smax is not None and k > smax:
            continue
        cross = _crosses(c.get("exp"), earnings_date)
        if avoid_earnings_cross and cross:
            continue
        dte = max(int(c.get("dte") or 1), 1)
        ret = m / k
        rows.append({**_base(c, m), "play": "cash_secured_put",
                     "credit_per_contract": round(m * 100, 2), "collateral_per_contract": round(k * 100, 2),
                     "return_pct": round(ret * 100, 3), "annualized_pct": round(ret * 365 / dte * 100, 1),
                     "breakeven": round(k - m, 4), "breakeven_vs_spot_pct": round((k - m) / spot * 100 - 100, 2),
                     "assignment_odds_pct": round(d * 100), "crosses_earnings": cross})
    rows.sort(key=lambda r: r["annualized_pct"], reverse=True)
    return rows[:top]


def rank_covered_calls(chain: Dict[str, Any], play: Dict[str, Any], *, thesis_target: Optional[float] = None,
                       shares_by_account: Optional[Dict[str, float]] = None, earnings_date: Optional[str] = None,
                       avoid_earnings_cross: bool = False, liq: Optional[Dict[str, Any]] = None,
                       top: int = 5) -> List[Dict[str, Any]]:
    """Covered calls that respect the intent: never below `min_strike`; ranked by premium among the
    strikes that keep the upside the operator asked for."""
    spot = _f(chain.get("underlying_price"))
    if not spot:
        return []
    floor = cc_strike_floor(play, spot=spot, thesis_target=thesis_target)
    contracts_avail = sum(int((s or 0) // 100) for s in (shares_by_account or {}).values())
    rows = []
    for c in contracts(chain, "call"):
        m, k = mid(c), _f(c.get("strike"))
        d = abs(_f(c.get("delta")) or 0)
        if not m or k is None or k <= spot or not liquid(c, liq):
            continue
        if floor is not None and k < floor:
            continue
        if not _in(c.get("dte"), play.get("dte")) or not _in(d, play.get("delta")):
            continue
        cross = _crosses(c.get("exp"), earnings_date)
        if avoid_earnings_cross and cross:
            continue
        dte = max(int(c.get("dte") or 1), 1)
        rows.append({**_base(c, m), "play": "covered_call",
                     "credit_per_contract": round(m * 100, 2), "contracts_available": contracts_avail,
                     "yield_pct": round(m / spot * 100, 3), "annualized_pct": round(m / spot * 365 / dte * 100, 1),
                     "upside_kept_pct": round((k / spot - 1) * 100, 1), "called_away_odds_pct": round(d * 100),
                     "below_thesis_target": bool(thesis_target and k < thesis_target), "crosses_earnings": cross})
    rows.sort(key=lambda r: r["credit_per_contract"], reverse=True)
    return rows[:top]


def rank_leaps(chain: Dict[str, Any], play: Dict[str, Any], *, top: int = 4) -> List[Dict[str, Any]]:
    """Deep-ITM long-dated calls (stock substitute / PMCC base), most liquid first."""
    spot = _f(chain.get("underlying_price"))
    if not spot:
        return []
    min_dte = int(play.get("min_dte", 300))
    min_delta = float(play.get("min_delta", 0.7))
    rows = []
    for c in contracts(chain, "call"):
        m, k = mid(c), _f(c.get("strike"))
        if not m or k is None or int(c.get("dte") or 0) < min_dte or abs(_f(c.get("delta")) or 0) < min_delta:
            continue
        if not c.get("two_sided"):
            continue
        ext = m - max(0.0, spot - k)
        rows.append({**_base(c, m), "play": "leap_call", "cost_per_contract": round(m * 100, 2),
                     "stock_cost_100": round(spot * 100, 2), "time_value": round(ext, 4),
                     "time_value_pct": round(ext / spot * 100, 2)})
    rows.sort(key=lambda r: -(r.get("oi") or 0))
    return rows[:top]


def cc_strike_floor(play: Dict[str, Any], *, spot: Optional[float], thesis_target: Optional[float]) -> Optional[float]:
    """Lowest covered-call strike the intent allows. An explicit `min_strike` wins; otherwise
    `keep_upside_pct` above spot. None = no floor (the generic desk rules apply)."""
    ms = _f((play or {}).get("min_strike"))
    if ms is not None:
        return ms
    kp = _f((play or {}).get("keep_upside_pct"))
    if kp is not None and spot:
        return spot * (1 + kp / 100.0)
    return None


def best_key(rows: List[Dict[str, Any]]) -> Optional[Tuple[str, float]]:
    """Identity + value of the leading contract — what a 'material change' compares."""
    if not rows:
        return None
    r = rows[0]
    return (str(r.get("contract") or f"{r.get('exp')}:{r.get('strike')}"),
            float(r.get("annualized_pct") or r.get("credit_per_contract") or 0))
