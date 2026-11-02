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
    """``{state: GREEN|AMBER|RED|UNKNOWN, candidates: [inverse…], benches: [bench…], as_of, reason}`` across the
    actionable lane. The one thesis reader: the Home Hedge block (``market_risk_home_actions.hedge``) calls it too."""
    if not isinstance(snap, dict) or not snap.get("candidates"):
        return {"state": "UNKNOWN", "candidates": [], "benches": [], "as_of": None, "reason": "no stoplight evaluation yet"}
    if snap.get("config_error"):
        return {"state": "UNKNOWN", "candidates": [], "benches": [], "as_of": snap.get("generated_at"), "reason": "stoplight config error"}
    d = _snapshot_date(snap)
    if d is None or (today - d).days > int(stale_days):
        return {
            "state": "UNKNOWN",
            "candidates": [],
            "benches": [],
            "as_of": snap.get("generated_at"),
            "reason": "stale",
            "last_ran": d.isoformat() if d else None,
        }
    by_state: dict[str, list[dict[str, Any]]] = {}
    for c in snap.get("candidates") or []:
        st = str(((c.get("lights") or {}).get("THESIS") or {}).get("state") or "UNKNOWN").upper()
        by_state.setdefault(st, []).append(c)
    for st in ("GREEN", "AMBER", "RED"):
        if by_state.get(st):
            return {"state": st, "candidates": [str(c.get("inverse") or "?") for c in by_state[st]],
                    "benches": [str(c.get("bench") or "").upper() for c in by_state[st]],
                    "as_of": snap.get("generated_at"), "reason": None}
    return {"state": "UNKNOWN", "candidates": [], "benches": [], "as_of": snap.get("generated_at"), "reason": "no THESIS light"}


def _ts(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(v))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


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
    green_since: Any = None,
) -> dict[str, Any]:
    """The posture's ``hedge_state``. ``intent`` = (status, fill_price, symbol) of the newest inverse-ETF intent;
    ``bounce`` = (symbol, threshold, last_fired_at[, armed_at]) of an active ``defense_hedge`` bounce alert;
    ``green_since`` = the newest THESIS → GREEN transition (a datetime, or {instrument: datetime} from which the GREEN
    candidates' newest is taken); ``in_play_line`` is the caller's
    formatted in-play line (it reads the last close).

    A bounce level is shown only when it belongs to THIS green episode (review of #2460, B2): the alert's bench is a
    GREEN candidate's bench AND it was armed at or after ``green_since``. An alert left from an earlier episode, or
    one whose arming time or the episode start is unknown, is never shown."""
    if tech_state not in ("LAGGING", "WEAKENING", None) and intent:
        return {"state": "stand_down", "line": f"HEDGE: stand-down signaled — Technology recovered to {tech_state}"}
    if intent and intent[0] == "filled":
        return {"state": "in_play", "line": in_play_line or f"HEDGE: {intent[2]} in play", **(close_meta or {})}
    th = stoplight_thesis(stoplights, today=today, stale_days=stale_days)
    if th["state"] == "UNKNOWN":
        why = f"stoplight last ran {th.get('last_ran') or 'unknown'} (older than {stale_days} days)" if th["reason"] == "stale" else th["reason"]
        return {"state": "unknown", "line": f"HEDGE: no verdict — {why}", "stoplight_as_of": th["as_of"]}
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
    # THESIS GREEN: the bounce-day entry rule applies, with this episode's alert only
    armed = _ts(bounce[3]) if bounce and len(bounce) > 3 else None
    if isinstance(green_since, dict):  # {instrument: newest GREEN transition}: this episode = the GREEN candidates' latest
        stamps = [_ts(green_since.get(c.upper())) for c in th["candidates"]]
        since = max((t for t in stamps if t is not None), default=None)
    else:
        since = _ts(green_since)
    live = bool(bounce) and str(bounce[0]).upper() in th["benches"] and armed is not None and since is not None and armed >= since
    if not live:
        return {"state": "armed", "line": f"HEDGE: thesis green ({'/'.join(th['candidates'])}) — bounce level arming tonight",
                "stoplight_as_of": th["as_of"]}
    if bounce[2] and str(bounce[2])[:10] == today.isoformat() and (_ts(bounce[2]) or since) >= since:
        return {"state": "entry_window_open", "line": f"HEDGE: entry window OPEN — {bounce[0]} bounce ≥ ${bounce[1]}",
                "stoplight_as_of": th["as_of"]}
    return {"state": "armed", "line": f"HEDGE: waiting for a bounce day ({bounce[0]} ≥ ${bounce[1]})", "stoplight_as_of": th["as_of"]}
