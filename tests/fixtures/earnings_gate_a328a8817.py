"""The earnings gate EXACTLY as the release that alerted AXTI at 10:20 ET on 2026-09-28 ran it.

Extracted verbatim from `git show a328a8817:scripts/options_desk_enterprise.py` (module sha256 619d8f2e1ccb41c7…):
line 27 (BLOCKING_STRATEGIES) and the body of earnings_blackout_check (lines 388-460). Only the two
collaborators it reaches are replaced by injectable stand-ins: load_desk_config (blackout days) and
earnings_calendar (the event date), plus `today` so the replay runs on the incident clock. Nothing in
the decision logic is altered. This module exists so the replay test can PROVE what the old release
decided; it must never be imported by production code.

Served at 10:20 ET: CURRENT -> a328a8817-main-exact-phase2-20260928-101406 (promoted 14:14:47Z, replaced
by e2dcfce1a at 14:59:24Z). PR #1336 (3adcd0104, merged 2745133e3 at 14:47:40Z) later added
debit_spread / long_put / leaps_call to the set.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

BLOCKING_STRATEGIES = frozenset({"covered_call", "cash_secured_put", "credit_spread", "long_call"})
EARNINGS_UNKNOWN = "__EARNINGS_UNKNOWN__"
_EARNINGS_LAST_ERROR = ""


def load_desk_config() -> dict:
    return {"earnings_blackout_days": 14}


def earnings_calendar(symbols):  # replaced by the test
    return {}


def earnings_blackout_check(
    symbol: str,
    *,
    dte: int,
    strategy: str,
    blackout_days: Optional[int] = None,
    today: Optional[date] = None,
) -> dict:
    """Return blackout status for short premium / directional entries near earnings."""
    cfg = load_desk_config()
    days = int(blackout_days or cfg.get("earnings_blackout_days") or 14)
    sym = (symbol or "").upper()
    if strategy not in BLOCKING_STRATEGIES:
        return {"in_blackout": False, "symbol": sym, "strategy": strategy}
    cal = earnings_calendar([sym])
    earn_raw = cal.get(sym) or ""
    if earn_raw == EARNINGS_UNKNOWN:
        return {
            "in_blackout": True,
            "symbol": sym,
            "strategy": strategy,
            "next_earnings": None,
            "days_to_earnings": None,
            "data_blocked": True,
            "refusal_code": "EARNINGS_TIMESTAMP_UNKNOWN",
            "reason": (f"Earnings timing unavailable — provider error "
                       f"({_EARNINGS_LAST_ERROR[:120] or 'unknown'}); "
                       f"{strategy} fails closed until an earnings source is restored"),
        }
    if not earn_raw:
        return {"in_blackout": False, "symbol": sym, "next_earnings": None, "days_to_earnings": None}
    try:
        if not isinstance(earn_raw, (str, date)):
            raise TypeError(f"non-date earnings value of type {type(earn_raw).__name__}")
        earn_dt = earn_raw if isinstance(earn_raw, date) else date.fromisoformat(str(earn_raw)[:10])
    except (ValueError, TypeError) as e:
        return {
            "in_blackout": True,
            "symbol": sym,
            "strategy": strategy,
            "next_earnings": None,
            "days_to_earnings": None,
            "data_blocked": True,
            "refusal_code": "EARNINGS_TIMESTAMP_INVALID",
            "raw_value": str(earn_raw)[:60],
            "reason": (f"Earnings value {str(earn_raw)[:40]!r} is not a usable date "
                       f"({e}) — {strategy} fails closed on unparseable event timing"),
        }
    today = today or date.today()
    days_to = (earn_dt - today).days
    # Block if earnings falls before expiration or within blackout window
    in_window = 0 <= days_to <= days
    expires_before_earn = dte >= days_to > 0
    in_blackout = in_window or expires_before_earn
    return {
        "in_blackout": in_blackout,
        "symbol": sym,
        "strategy": strategy,
        "next_earnings": earn_dt.isoformat(),
        "days_to_earnings": days_to,
        "blackout_days": days,
        "reason": (
            f"Earnings {earn_dt} in {days_to}d — inside {days}d blackout"
            if in_blackout else ""
        ),
    }
