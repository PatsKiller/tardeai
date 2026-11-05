"""The A1/A2 decision rules for critical "act now" texts (SPEC_CRITICAL_TEXT_ACTION_ALERTS_20261104).

Pure functions: numbers in, an event for ``critical_texts.send_critical_text`` out, or ``None``. Nothing here
reads a quote, calls a broker, schedules a loop or computes a stop policy — the caller supplies the extended-hours
price, the live stop and (for A2) the stop the existing stop code already recommends. That keeps the replay the
spec's acceptance asks for (the 10-30 selloff, the SPCX card) a fixture test rather than a live run.
"""

from __future__ import annotations

import math
from typing import Any, Optional

A1 = "A1_extended_hours_near_stop"
A2 = "A2_stop_not_raised_after_move"

#: Suggested limit sits this far under the extended-hours price: close enough to fill, above the stop.
DEFAULT_UNDERCUT_PCT = 0.25


def _num(value: Any) -> Optional[float]:
    """A real finite number, or None. Bools, strings, NaN and infinities are not measurements."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value: Optional[float]) -> str:
    return f"{value:,.2f}" if value is not None else "unknown"


def extended_hours_near_stop(
    symbol: str,
    account: Optional[str],
    ext_price: Any,
    stop: Any,
    *,
    within_pct: float = 2.0,
    retext_step_pct: float = 1.0,
    last_texted_price: Any = None,
    undercut_pct: float = DEFAULT_UNDERCUT_PCT,
    session_label: str = "ext-hrs",
    stop_inactive_until: str = "9:30",
    date_key: str = "",
) -> Optional[dict[str, Any]]:
    """A1: the extended-hours price is at or within ``within_pct`` of a stop that cannot fire yet.

    Re-texts only after a further ``retext_step_pct`` drop below the price already texted, so a slow bleed cannot
    page the operator on every tick.
    """
    price, level = _num(ext_price), _num(stop)
    if not symbol or price is None or level is None or price <= 0 or level <= 0:
        return None
    if price > level * (1 + within_pct / 100.0):
        return None
    previous = _num(last_texted_price)
    if previous is not None and price > previous * (1 - retext_step_pct / 100.0):
        return None
    # Round UP to the nearest nickel: a limit that fills beats a limit that is a cent prettier.
    limit = round(math.ceil(price * (1 - undercut_pct / 100.0) / 0.05) * 0.05, 2)
    where = f" ({account})" if account else ""
    trigger = f"{session_label} {price:,.2f}, stop {level:,.2f} inactive till {stop_inactive_until}"
    text = f"EXT limit sell {_money(limit)}"
    return {
        "alert_class": A1,
        "event_id": f"{symbol.upper()}:A1:{date_key}:{price:.2f}",
        "symbol": symbol.upper(),
        "account": account,
        "trigger": trigger,
        "action": text,
        "suggested_limit": limit,
        "distance_pct": round((price - level) / level * 100.0, 2),
        "summary": f"EXT limit sell {_money(limit)} on {symbol.upper()}{where}",
    }


def stop_not_raised(
    symbol: str,
    account: Optional[str],
    live_stop: Any,
    recommended_stop: Any,
    *,
    move_1d_pct: Any,
    move_5d_pct: Any = None,
    up_pct: float = 8.0,
    up5_pct: float = 15.0,
    tol_pct: float = 2.0,
    shares: Any = None,
    price: Any = None,
    date_key: str = "",
) -> Optional[dict[str, Any]]:
    """A2: a big move left the live stop below the stop the system's own policy already recommends.

    It computes no stop of its own — ``recommended_stop`` comes from the existing stop code, which is the point:
    two definitions of "the stop it should have" would be one too many. Fires once per symbol/date.
    """
    one_day, five_day = _num(move_1d_pct), _num(move_5d_pct)
    live, target = _num(live_stop), _num(recommended_stop)
    if not symbol or target is None or target <= 0:
        return None
    high_1d = one_day is not None and one_day >= up_pct
    high_5d = five_day is not None and five_day >= up5_pct
    if not (high_1d or high_5d):
        return None
    if live is not None and live >= target * (1 - tol_pct / 100.0):
        return None                                   # already raised far enough
    held = _num(shares)
    at_risk = None
    if held is not None and held > 0 and live is not None:
        mark = _num(price)
        if mark is not None:
            at_risk = round((mark - live) * held, 2)
    moved = f"{one_day:+.1f}% in 1 day" if high_1d else f"{five_day:+.1f}% in 5 days"
    trigger = (f"{moved}, stop {_money(live) if live is not None else 'missing'} "
               f"vs recommended {target:,.2f}")
    if at_risk is not None:
        trigger += f", {at_risk:,.0f} at risk"
    return {
        "alert_class": A2,
        "event_id": f"{symbol.upper()}:A2:{date_key}",
        "symbol": symbol.upper(),
        "account": account,
        "trigger": trigger,
        "action": f"Raise stop to {target:,.2f}",
        "recommended_stop": target,
        "live_stop": live,
        "gain_at_risk_usd": at_risk,
    }
