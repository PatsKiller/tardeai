"""The Defense posture's one-line hedge state, decided by the inverse-hedge stoplight (design home/v006).

Before 2026-11-01 ``GET /api/v2/defense/posture`` built ``hedge_state`` from whichever ``defense_hedge`` bounce alert
row it found in ``watch_alerts``, with no active, thesis or date check. The nightly playbook arms those alerts while
a HEDGE card is live and nothing deactivates them when the trigger ends, so on 2026-11-01 the posture still said
"waiting for a bounce day (QQQ >= $720.48)" two sessions after the stoplight turned THESIS RED ("NO BEARISH THESIS")
for every inverse candidate. A stale alert must never read as a live hedge plan.

Rule (first match):

1. A recorded inverse-ETF intent that is ``filled`` (or a stand-down after one) keeps its existing line: a hedge in
   play is reported whatever the stoplight says.
2. The stoplight snapshot is missing, unreadable, carries a ``config_error`` or is older than
   ``inverse_stoplights.stale_calendar_days``: state ``unknown``. No bounce level is shown.
3. No actionable candidate has THESIS GREEN: state ``no_thesis`` (THESIS RED everywhere) or ``watch`` (any AMBER),
   with the stoplight's own label. No bounce level is shown, whatever ``watch_alerts`` holds.
4. THESIS GREEN: the previous behaviour (entry window open today, or waiting for a bounce day at the alert level).

Pure function; the caller does the reads. Advisory text only (MBI_BEHAVIOR = 0): no size, order or stop.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def _snapshot_date(snap: dict[str, Any]) -> date | None:
    try:
        return datetime.fromisoformat(str(snap.get("generated_at"))).astimezone(timezone.utc).date()
    except (TypeError, ValueError):
        return None


def stoplight_thesis(snap: dict[str, Any] | None, *, today: date, stale_days: int) -> dict[str, Any]:
    """``{state: GREEN|AMBER|RED|UNKNOWN, candidates: [inverse…], as_of, reason}`` across the actionable lane."""
    if not isinstance(snap, dict) or not snap.get("candidates"):
        return {"state": "UNKNOWN", "candidates": [], "as_of": None, "reason": "no stoplight evaluation yet"}
    if snap.get("config_error"):
        return {"state": "UNKNOWN", "candidates": [], "as_of": snap.get("generated_at"), "reason": "stoplight config error"}
    d = _snapshot_date(snap)
    if d is None or (today - d).days > int(stale_days):
        return {
            "state": "UNKNOWN",
            "candidates": [],
            "as_of": snap.get("generated_at"),
            "reason": f"stoplight last ran {d.isoformat() if d else 'unknown'} (older than {stale_days} days)",
        }
    by_state: dict[str, list[str]] = {}
    for c in snap.get("candidates") or []:
        st = str(((c.get("lights") or {}).get("THESIS") or {}).get("state") or "UNKNOWN").upper()
        by_state.setdefault(st, []).append(str(c.get("inverse") or "?"))
    for st in ("GREEN", "AMBER", "RED"):
        if by_state.get(st):
            return {"state": st, "candidates": by_state[st], "as_of": snap.get("generated_at"), "reason": None}
    return {"state": "UNKNOWN", "candidates": [], "as_of": snap.get("generated_at"), "reason": "no THESIS light"}


def hedge_state(
    *,
    stoplights: dict[str, Any] | None,
    intent: tuple | None,
    bounce: tuple | None,
    tech_state: str | None,
    today: date,
    stale_days: int,
    in_play_line: str | None = None,
    close_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The posture's ``hedge_state``. ``intent`` = (status, fill_price, symbol) of the newest inverse-ETF intent;
    ``bounce`` = (symbol, threshold, last_fired_at) of a ``defense_hedge`` bounce alert; ``in_play_line`` is the
    caller's formatted in-play line (it reads the last close)."""
    if tech_state not in ("LAGGING", "WEAKENING", None) and intent:
        return {"state": "stand_down", "line": f"HEDGE: stand-down signaled — Technology recovered to {tech_state}"}
    if intent and intent[0] == "filled":
        return {"state": "in_play", "line": in_play_line or f"HEDGE: {intent[2]} in play", **(close_meta or {})}
    th = stoplight_thesis(stoplights, today=today, stale_days=stale_days)
    if th["state"] == "UNKNOWN":
        return {"state": "unknown", "line": f"HEDGE: no verdict — {th['reason']}", "stoplight_as_of": th["as_of"]}
    if th["state"] == "RED":
        return {
            "state": "no_thesis",
            "line": "HEDGE: not needed now — inverse stoplight shows no bearish thesis",
            "stoplight_as_of": th["as_of"],
        }
    if th["state"] == "AMBER":
        return {
            "state": "watch",
            "line": f"HEDGE: watch — deteriorating, not yet eligible ({'/'.join(th['candidates'])})",
            "stoplight_as_of": th["as_of"],
        }
    # THESIS GREEN: the bounce-day entry rule applies
    if bounce and bounce[2] and str(bounce[2])[:10] == today.isoformat():
        return {"state": "entry_window_open", "line": f"HEDGE: entry window OPEN — {bounce[0]} bounce ≥ ${bounce[1]}",
                "stoplight_as_of": th["as_of"]}
    return {
        "state": "armed",
        "line": f"HEDGE: waiting for a bounce day ({bounce[0]} ≥ ${bounce[1]})" if bounce else "HEDGE: alerts arming tonight",
        "stoplight_as_of": th["as_of"],
    }
