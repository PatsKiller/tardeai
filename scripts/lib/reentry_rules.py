"""Re-entry rules — the deterministic READY / NEAR / WAIT classifier of the Re-Entry Decision Desk.

Moved verbatim out of ``scripts/lib/data_broker/reentry_decision_desk.py`` (2026-10-22) so the CIO prospect shadow
lane can reuse the SAME logic (AGENTS.md §13.5: one implementation; the operator asked for re-entry advice that
"reuses the re-entry desk logic, not a parallel one") without importing the desk module, whose import closure
reaches the market-quote provider and broker transport (a dispatched lane may not import those, §23.14).
``reentry_decision_desk`` re-exports every name below, so its callers and behaviour are unchanged.

Pure: no I/O, no imports beyond the standard library. No LLM on this path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

STALE_HOURS = 96
NEAR_PCT = 3.0
RSI_READY_LOW = 40.0
RSI_READY_HIGH = 70.0
RSI_OVERSOLD = 30.0
WASH_DAYS = 30


def _age_hours(as_of: str | None) -> float | None:
    """Hours since quote timestamp. Accepts ISO and broker forms like '2026-08-01 07:35:12 ET'."""
    if not as_of:
        return None
    s = str(as_of).strip()
    if not s:
        return None
    try:
        import re
        from zoneinfo import ZoneInfo

        m = re.match(r"^(.+?)\s+(ET|EST|EDT|UTC|GMT|Z)$", s, re.I)
        if m:
            body, tz = m.group(1).strip(), m.group(2).upper()
            if "T" not in body and " " in body:
                body = body.replace(" ", "T", 1)
            naive = datetime.fromisoformat(body)
            if tz in ("ET", "EST", "EDT"):
                ts = naive.replace(tzinfo=ZoneInfo("America/New_York"))
            else:
                ts = naive.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                # Naive market quotes are Eastern unless explicitly UTC/Z
                try:
                    ts = ts.replace(tzinfo=ZoneInfo("America/New_York"))
                except Exception:
                    ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return None


def _weekend_fresh_ok(age_h: float | None, *, stale_hours: float = STALE_HOURS) -> bool:
    """True when quote is within stale_hours, or is a Friday RTH print held over Sat/Sun.

    Operators decide on weekends from last session quotes — do not fail freshness solely
    because the calendar crossed into Saturday/Sunday.
    """
    if age_h is None:
        return False
    if age_h <= stale_hours:
        return True
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
        # Sat=5, Sun=6 — allow up to Fri 16:00 → Sun night (~56h) plus buffer to stale_hours
        if now_et.weekday() >= 5 and age_h <= max(stale_hours, 72.0):
            return True
    except Exception:
        pass
    return False


def derive_intel_state(
    *,
    price: float | None,
    rsi: float | None,
    as_of: str | None,
    entry_low: float | None,
    entry_high: float | None,
    held: bool,
    wash_blocked: bool = False,
) -> dict[str, Any]:
    """Canonical READY band: in zone + 40 <= RSI < 70 (matches rotation gates)."""
    age_h = _age_hours(as_of)
    stale = age_h is None or not _weekend_fresh_ok(age_h)

    distance_pct = None
    if price is not None and entry_low is not None and entry_high is not None and entry_low > 0 and entry_high > 0:
        if price > entry_high:
            distance_pct = ((price - entry_high) / entry_high) * 100
        elif price < entry_low:
            distance_pct = -((entry_low - price) / entry_low) * 100
        else:
            distance_pct = 0.0

    state = "WAIT"
    action = "Keep monitoring"
    reason = "Current price has not reached the validated entry conditions."

    if held:
        state, action, reason = (
            "CURRENTLY HELD",
            "Manage as an existing holding",
            "This symbol is currently held and is not a clean re-entry-only candidate.",
        )
    elif wash_blocked:
        state, action, reason = (
            "WASH BLOCK",
            "Wait for wash window",
            f"Exit within {WASH_DAYS} days — wash-sale window still open (deterministic).",
        )
    elif price is None or rsi is None:
        state, action, reason = (
            "MISSING MARKET",
            "Refresh market evidence",
            "Current price and RSI from the data broker are required before a re-entry review.",
        )
    elif stale:
        state, action, reason = (
            "STALE",
            "Refresh inputs",
            f"Market/technical evidence is stale ({age_h:.0f}h)." if age_h is not None
            else "Market/technical evidence timestamp is unavailable or too old.",
        )
    elif entry_low is None or entry_high is None:
        state, action, reason = (
            "MISSING PLAN",
            "Build a candidate entry zone",
            "Market evidence exists, but no current validated entry range is available.",
        )
    elif rsi >= RSI_READY_HIGH:
        state, action, reason = (
            "OVERBOUGHT WAIT",
            "Wait for RSI to cool",
            f"RSI {rsi:.1f} is overbought (>= {RSI_READY_HIGH:.0f}); not a re-entry review.",
        )
    elif distance_pct == 0 and rsi <= RSI_OVERSOLD:
        state, action, reason = (
            "OVERSOLD REVIEW",
            "Review with caution",
            f"Price is in zone but RSI {rsi:.1f} is oversold (<= {RSI_OVERSOLD:.0f}) — not full READY.",
        )
    elif distance_pct == 0 and RSI_READY_LOW <= rsi < RSI_READY_HIGH:
        state, action, reason = (
            "READY TO REVIEW",
            "Review re-entry now",
            f"Price is inside the entry zone and RSI {rsi:.1f} is in the constructive band "
            f"({RSI_READY_LOW:.0f}–{RSI_READY_HIGH:.0f}).",
        )
    elif distance_pct == 0 and rsi < RSI_READY_LOW:
        # Between oversold floor and READY band (e.g. RSI 31–39): not READY yet.
        state, action, reason = (
            "WAIT",
            "Wait for RSI to strengthen",
            f"Price is in zone but RSI {rsi:.1f} is below the constructive band "
            f"({RSI_READY_LOW:.0f}–{RSI_READY_HIGH:.0f}).",
        )
    elif distance_pct is not None and 0 < distance_pct <= NEAR_PCT and rsi < RSI_READY_HIGH:
        state, action, reason = (
            "NEAR ENTRY",
            "Prepare the review",
            f"Price is {distance_pct:.1f}% above the entry zone; RSI {rsi:.1f} is not overbought.",
        )
    elif distance_pct is not None and 0 < distance_pct <= NEAR_PCT and rsi >= RSI_READY_HIGH:
        state, action, reason = (
            "OVERBOUGHT WAIT",
            "Wait for RSI to cool",
            f"Near zone but RSI {rsi:.1f} is overbought.",
        )

    return {
        "state": state,
        "action": action,
        "reason": reason,
        "distance_pct": round(distance_pct, 3) if distance_pct is not None else None,
        "chips": [],
        "criteria": {
            "rsi_band": f"{RSI_READY_LOW:.0f} <= RSI < {RSI_READY_HIGH:.0f}",
            "near_pct": NEAR_PCT,
            "stale_hours": STALE_HOURS,
            "deterministic": True,
            "llm_in_path": False,
        },
    }
