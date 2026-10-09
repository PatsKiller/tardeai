"""Market-hours-aware monitor for the 5-minute scalp lane (trade-ai-scalp-live), from ScalpCycleReceipt@v1.

Workstream B4 of the n8n maturity program (2026-10-09). Rules (docs/implementation/n8n-maturity/
03-momentum-scalp-lanes.md, "Monitoring"):

- Expected slots: every ``cadence_min`` slot whose start is inside the REGULAR session (09:30 to the close,
  13:00 on early-close days; none on weekends and holidays). A slot is *due* once its start plus the
  deadline has passed.
- A slot is OK when it has a final ``ok`` receipt finished within the deadline. Anything else (no record,
  ``started`` only, ``killed``, ``error``, ``ok`` past the deadline) is a MISSED slot.
- Heartbeat: STALE only during RTH, when the last OK cycle finished more than 2x cadence ago (10 min).
  Outside RTH the lane is never stale, so the watcher stays quiet overnight and on holidays.
- Incidents: P2 ``trade-ai-scalp-live:MISSED_CYCLES`` when the latest due slots include a run of >= 2
  consecutive misses; P1 ``trade-ai-scalp-live:NO_CYCLES_30M`` when no cycle finished OK for >= 30 min
  of RTH.
- Clean RTH day (shadow/cutover gate): >= 95% of the day's slots OK, no 30-min gap, <= 1 P2 episode.

Pure: no network, no Telegram. ``session_fn(dt) -> str`` is scripts/market_session.current_market_session
(injected in tests).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

import scalp_cycle_receipt as scr

ET = ZoneInfo("America/New_York")
SCHEMA = "ScalpCycleMonitor@v1"
CADENCE_MIN = 5
DEADLINE_S = 295
STALE_FACTOR = 2            # stale at 2x cadence, RTH only
P2_CONSECUTIVE = 2          # 2 missed RTH cycles in a row
P1_GAP_MIN = 30             # 30 min of RTH without an OK cycle
CLEAN_OK_RATE = 0.95
CLEAN_MAX_P2 = 1


def _default_session_fn(dt: datetime) -> str:
    from market_session import current_market_session

    return current_market_session(dt)


def rth_slots(day: str, session_fn: Callable[[datetime], str], cadence_min: int = CADENCE_MIN) -> list[datetime]:
    """Slot starts (ET) of one day that fall in the regular session."""
    d = datetime.fromisoformat(day).replace(tzinfo=ET)
    out = []
    t = d.replace(hour=9, minute=30)
    end = d.replace(hour=16, minute=0)
    while t < end:
        if session_fn(t) == "regular":
            out.append(t)
        t += timedelta(minutes=cadence_min)
    return out


def _parse(ts: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts)) if ts else None
    except ValueError:
        return None


def slot_state(rec: Optional[dict[str, Any]], deadline_s: float) -> str:
    if rec is None:
        return "missing"
    st = rec.get("status")
    if st == "ok":
        sec = rec.get("seconds")
        return "ok" if sec is None or float(sec) <= deadline_s else "late"
    if st == "started":
        return "lost"
    return str(st or "missing")


def _p2_episodes(states: list[str]) -> int:
    n = run = 0
    for s in states:
        if s == "ok":
            run = 0
            continue
        run += 1
        if run == P2_CONSECUTIVE:
            n += 1
    return n


def evaluate(records: Iterable[dict[str, Any]], now: datetime, *, day: Optional[str] = None,
             session_fn: Optional[Callable[[datetime], str]] = None, cadence_min: int = CADENCE_MIN,
             deadline_s: float = DEADLINE_S, lane_id: str = scr.LANE_ID) -> dict[str, Any]:
    session_fn = session_fn or _default_session_fn
    now_et = now.astimezone(ET)
    day = day or now_et.date().isoformat()
    folded = scr.fold(records)
    slots = rth_slots(day, session_fn, cadence_min)
    in_rth = session_fn(now_et) == "regular" and now_et.date().isoformat() == day
    due = [s for s in slots if s + timedelta(seconds=deadline_s) <= now_et]
    states = [slot_state(folded.get(f"{s:%H:%M}"), deadline_s) for s in due]
    ok_slots = [s for s, st in zip(due, states) if st == "ok"]
    counts: dict[str, int] = {}
    for st in states:
        counts[st] = counts.get(st, 0) + 1

    ok_finishes = sorted(f for f in (_parse(folded[f"{s:%H:%M}"].get("finished_at")) for s in ok_slots) if f)
    last_ok = ok_finishes[-1] if ok_finishes else None
    last_ok_age_min = None if last_ok is None else round((now_et - last_ok).total_seconds() / 60, 1)

    # longest RTH stretch without an OK finish (session open -> first ok, ok -> ok, last ok -> now/close)
    max_gap_min = 0.0
    if slots:
        open_t = slots[0]
        close_t = min(now_et, slots[-1] + timedelta(minutes=cadence_min))
        marks = [open_t] + [f for f in ok_finishes if open_t <= f <= close_t] + [close_t]
        if close_t > open_t:
            max_gap_min = round(max((b - a).total_seconds() / 60 for a, b in zip(marks, marks[1:])), 1)

    tail = 0
    for st in reversed(states):
        if st == "ok":
            break
        tail += 1
    since_open_min = (now_et - slots[0]).total_seconds() / 60 if (in_rth and slots) else 0
    rth_gap_min = None
    if in_rth:
        rth_gap_min = round(since_open_min if last_ok is None else (now_et - last_ok).total_seconds() / 60, 1)
    stale = bool(in_rth and since_open_min >= STALE_FACTOR * cadence_min + deadline_s / 60
                 and rth_gap_min is not None and rth_gap_min > STALE_FACTOR * cadence_min)

    incidents: list[dict[str, Any]] = []
    detected = f"{day}T00:00:00+00:00"
    if in_rth and tail >= P2_CONSECUTIVE:
        incidents.append({"source": "scalp_cycles", "item": f"{lane_id}:MISSED_CYCLES", "severity": "P2",
                          "detail": f"{tail} consecutive RTH scalp cycles missed "
                                    f"(last slots: {', '.join(states[-tail:][-4:])})",
                          "artifact_rel": f"{scr.LEDGER_REL}/{day}.jsonl", "store": "data/runtime",
                          "detected_at": detected})
    if in_rth and rth_gap_min is not None and rth_gap_min >= P1_GAP_MIN:
        incidents.append({"source": "scalp_cycles", "item": f"{lane_id}:NO_CYCLES_30M", "severity": "P1",
                          "detail": f"no OK scalp cycle for {round(rth_gap_min)} min of RTH "
                                    f"(last ok {last_ok.isoformat() if last_ok else 'none today'})",
                          "artifact_rel": f"{scr.LEDGER_REL}/{day}.jsonl", "store": "data/runtime",
                          "detected_at": detected})

    finals = [folded[k] for k in folded if folded[k].get("status") in scr.FINAL_STATUSES]
    secs = sorted(float(r["seconds"]) for r in finals if r.get("status") == "ok" and r.get("seconds") is not None)
    median_s = None if not secs else secs[len(secs) // 2]
    alerts_sent = sum(int(r.get("alerts_sent") or 0) for r in finals)
    alerts_deduped = sum(int(r.get("alerts_deduped") or 0) for r in finals)
    signals = sum(int(r.get("signals") or 0) for r in finals)
    ok_rate = None if not due else round(len(ok_slots) / len(due), 3)
    p2_episodes = _p2_episodes(states)
    day_complete = bool(slots) and len(due) == len(slots)
    clean = None
    if day_complete:
        clean = bool(ok_rate is not None and ok_rate >= CLEAN_OK_RATE and max_gap_min < P1_GAP_MIN
                     and p2_episodes <= CLEAN_MAX_P2)

    if not slots:
        line = f"Scalp lane {day}: market closed (no RTH slots)"
    else:
        line = (f"Scalp lane {day}: {len(ok_slots)}/{len(due)} RTH cycles ok"
                + (f" ({round(100 * ok_rate)}%)" if ok_rate is not None else "")
                + (f", median {round(median_s)}s, max {round(secs[-1])}s/{int(deadline_s)}s" if secs else "")
                + f", {signals} GO signals, alerts {alerts_sent} sent/{alerts_deduped} deduped"
                + (f"; last ok {last_ok_age_min} min ago" if last_ok_age_min is not None else "; no ok cycle yet")
                + (f"; {', '.join(i['severity'] + ' ' + i['item'].split(':')[-1] for i in incidents)}"
                   if incidents else "")
                + ("" if clean is None else ("; CLEAN day" if clean else "; NOT clean")))
    return {
        "schema": SCHEMA, "lane_id": lane_id, "date": day, "as_of": now_et.isoformat(), "in_rth": in_rth,
        "cadence_min": cadence_min, "deadline_s": deadline_s,
        "slots_total": len(slots), "slots_due": len(due), "slots_ok": len(ok_slots), "slot_states": counts,
        "ok_rate": ok_rate, "missed_tail": tail, "p2_episodes": p2_episodes, "max_rth_gap_min": max_gap_min,
        "last_ok_at": None if last_ok is None else last_ok.isoformat(), "last_ok_age_min": last_ok_age_min,
        "stale": stale, "median_seconds": median_s, "max_seconds": secs[-1] if secs else None,
        "signals": signals, "alerts_sent": alerts_sent, "alerts_deduped": alerts_deduped,
        "incidents": incidents, "clean_day": clean, "summary_line": line,
    }
