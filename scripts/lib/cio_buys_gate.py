"""cio_buys_gate — the CIO synopsis "Buys" line (LQ-20261107-1311).

Operator 2026-11-08 20:05 ET: the preview said "make no new buys before Tuesday's CPI" and the live
brief did not say it at all. The posture ("DEFENSIVE — HOLD CASH") implied it but never named the
gate or when it lifts. This states it, deterministically, from two sourced inputs only: the
market-risk tier (runtime/market_risk/latest.json) and the week-ahead macro calendar. No model
decides it. Advisory only: it sizes nothing and places nothing.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence

#: Macro releases that move the whole tape at 08:30/14:00 ET. A buy gate waits for the first one.
MARKET_MOVING = ("consumer price index", "cpi", "producer price index", "ppi", "fomc", "federal funds",
                 "employment situation", "nonfarm", "payroll", "pce", "personal income")
SHORT = {"consumer price index": "CPI", "cpi": "CPI", "producer price index": "PPI", "ppi": "PPI",
         "employment situation": "jobs report", "nonfarm": "jobs report", "fomc": "FOMC", "pce": "PCE",
         "personal consumption": "PCE"}
#: How far ahead a release still gates buys (calendar days).
GATE_HORIZON_DAYS = 5


def _short(event: str) -> str:
    low = event.lower()
    for k, v in SHORT.items():
        if k in low:
            return v
    return event


def _when(d: str, t: Optional[str]) -> str:
    try:
        label = f"{date.fromisoformat(d[:10]):%a %m-%d}"
    except ValueError:
        label = d
    return f"{label} {t} ET" if t else label


def first_gating_event(macro: Sequence[Mapping[str, Any]], today: date) -> Optional[Mapping[str, Any]]:
    """The earliest market-moving release from ``today`` within the horizon, or None."""
    best = None
    for e in macro or []:
        name = str(e.get("event") or "").lower()
        try:
            d = date.fromisoformat(str(e.get("date") or "")[:10])
        except ValueError:
            continue
        if not any(k in name for k in MARKET_MOVING):
            continue
        if not (0 <= (d - today).days <= GATE_HORIZON_DAYS):
            continue
        if best is None or (d, str(e.get("time_et") or "")) < (best[0], str(best[1].get("time_et") or "")):
            best = (d, e)
    return best[1] if best else None


def buys_block(tier: Optional[str], macro: Sequence[Mapping[str, Any]], as_of: datetime) -> dict[str, Any]:
    """{line, gate, until, source_ids}. ``gate`` is NONE / SMALL_ONLY / OPEN / UNKNOWN."""
    tier = (tier or "").upper()
    ev = first_gating_event(macro, as_of.date())
    ev_txt = f"{_short(str(ev.get('event')))} {_when(str(ev.get('date')), ev.get('time_et'))}" if ev else None
    # "CPI Tue": the short form the one-line verdict carries.
    ev_short = " ".join(ev_txt.split()[:2]) if ev_txt else None
    src = ["market_risk", "macro_calendar"]
    if tier in ("RED", "ORANGE"):
        line = (f"No new buys before {ev_txt}; protect gains with stops, then re-check the risk tier after the print"
                if ev_txt else f"No new buys while the tier is {tier}; protect gains with stops")
        return {"line": line, "gate": "NONE", "until": ev_txt, "until_short": ev_short, "source_ids": src}
    if tier == "YELLOW":
        line = (f"Small sizes only, and nothing new before {ev_txt}" if ev_txt else "Small sizes only")
        return {"line": line, "gate": "SMALL_ONLY", "until": ev_txt, "until_short": ev_short, "source_ids": src}
    if tier == "GREEN":
        line = (f"Buys open, slowly; wait for {ev_txt} before adding size" if ev_txt else "Buys open, slowly")
        return {"line": line, "gate": "OPEN", "until": ev_txt, "until_short": ev_short, "source_ids": src}
    return {"line": "No buy call: the market-risk read is missing", "gate": "UNKNOWN", "until": ev_txt, "until_short": ev_short, "source_ids": src}
