#!/usr/bin/env python3
"""earnings_provider.py — single earnings-timing source of record for event gates.

Replaces the dead FMP path (v3/earning_calendar returns HTTP 403 for non-legacy
keys and the key is additionally quota-exhausted, verified 2026-07-20).

Resolution order per symbol:

  1. symbol_profiles.next_earnings_date — written daily 06:35 weekdays by
     scripts/earnings_enrich.py from yfinance, covering held stocks + the
     Hermes top-N watchlist. This is the internal record.
  2. On-demand yfinance lookup for symbols outside that coverage (the options
     desk proposes on names beyond held+watchlist), cached in-process.

Three-state result — the distinction the old code collapsed and which caused
every event gate to fail OPEN:

  EarningsInfo(state=SCHEDULED, date=<date>)  provider answered, date known
  EarningsInfo(state=NONE_SCHEDULED)          provider answered, nothing booked
  EarningsInfo(state=UNKNOWN, reason=...)     provider could not answer

UNKNOWN must fail closed at every call site. "No data" is never "no earnings".
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# A profile row whose earnings_updated_at is older than this is not trusted to
# mean "nothing scheduled" — it means we have not looked recently enough.
PROFILE_TRUST_DAYS = int(os.getenv("EARNINGS_PROFILE_TRUST_DAYS", "7"))

SCHEDULED = "SCHEDULED"
NONE_SCHEDULED = "NONE_SCHEDULED"
UNKNOWN = "UNKNOWN"

# in-process memo for on-demand lookups: symbol -> (EarningsInfo, fetched_at)
_ONDEMAND: Dict[str, tuple] = {}
_ONDEMAND_TTL_SEC = 6 * 3600


@dataclass(frozen=True)
class EarningsInfo:
    symbol: str
    state: str
    date: Optional[date] = None
    source: str = ""
    reason: str = ""

    @property
    def known(self) -> bool:
        return self.state in (SCHEDULED, NONE_SCHEDULED)

    def days_until(self, today: Optional[date] = None) -> Optional[int]:
        if self.state != SCHEDULED or not self.date:
            return None
        return (self.date - (today or date.today())).days


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _from_profiles(symbols: Iterable[str]) -> Dict[str, EarningsInfo]:
    """Read the internal record. Absent/stale rows are UNKNOWN, never 'none'."""
    syms = sorted({(s or "").upper() for s in symbols if s})
    if not syms:
        return {}
    out: Dict[str, EarningsInfo] = {}
    try:
        cur = _conn().cursor()
        cur.execute("""SELECT upper(symbol), next_earnings_date, earnings_updated_at
                       FROM symbol_profiles WHERE upper(symbol) = ANY(%s)""", (syms,))
        rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    except Exception as e:
        return {s: EarningsInfo(s, UNKNOWN, reason=f"symbol_profiles unreadable: {e}"[:120])
                for s in syms}

    now = datetime.now(timezone.utc)
    for s in syms:
        if s not in rows:
            out[s] = EarningsInfo(s, UNKNOWN, source="symbol_profiles",
                                  reason="no profile row — symbol outside enrichment coverage")
            continue
        nxt, updated = rows[s]
        if updated is None:
            out[s] = EarningsInfo(s, UNKNOWN, source="symbol_profiles",
                                  reason="profile row never earnings-enriched")
            continue
        age_days = (now - updated.astimezone(timezone.utc)).total_seconds() / 86400
        if age_days > PROFILE_TRUST_DAYS:
            out[s] = EarningsInfo(s, UNKNOWN, source="symbol_profiles",
                                  reason=f"earnings_updated_at {age_days:.0f}d stale "
                                         f"(>{PROFILE_TRUST_DAYS}d) — not trusted as 'none scheduled'")
            continue
        if nxt is None:
            # Looked recently, found nothing booked. Legitimate NONE.
            out[s] = EarningsInfo(s, NONE_SCHEDULED, source="symbol_profiles")
        else:
            out[s] = EarningsInfo(s, SCHEDULED, date=nxt, source="symbol_profiles")
    return out


def _from_yfinance(symbol: str) -> EarningsInfo:
    """On-demand lookup for symbols outside enrichment coverage."""
    s = symbol.upper()
    hit = _ONDEMAND.get(s)
    if hit and (datetime.now(timezone.utc) - hit[1]).total_seconds() < _ONDEMAND_TTL_SEC:
        return hit[0]
    try:
        import yfinance as yf
        from earnings_enrich import _extract
        ed = yf.Ticker(s).get_earnings_dates(limit=12)
        if ed is None or getattr(ed, "empty", False):
            info = EarningsInfo(s, NONE_SCHEDULED, source="yfinance_ondemand")
        else:
            nxt, *_ = _extract(ed)
            info = (EarningsInfo(s, SCHEDULED, date=nxt, source="yfinance_ondemand")
                    if nxt else EarningsInfo(s, NONE_SCHEDULED, source="yfinance_ondemand"))
    except Exception as e:
        info = EarningsInfo(s, UNKNOWN, source="yfinance_ondemand",
                            reason=f"yfinance lookup failed: {e}"[:120])
    _ONDEMAND[s] = (info, datetime.now(timezone.utc))
    return info


def get_earnings(symbols: Iterable[str], *, allow_ondemand: bool = True) -> Dict[str, EarningsInfo]:
    """Resolve earnings timing for symbols. Never raises; UNKNOWN carries the reason."""
    syms = sorted({(s or "").upper() for s in symbols if s})
    resolved = _from_profiles(syms)
    if allow_ondemand:
        for s in syms:
            if resolved.get(s) and resolved[s].state == UNKNOWN:
                od = _from_yfinance(s)
                if od.known:
                    resolved[s] = od
                else:
                    resolved[s] = EarningsInfo(
                        s, UNKNOWN, source="symbol_profiles+yfinance",
                        reason=f"{resolved[s].reason}; on-demand: {od.reason}"[:200])
    return resolved


def get_one(symbol: str, *, allow_ondemand: bool = True) -> EarningsInfo:
    return get_earnings([symbol], allow_ondemand=allow_ondemand).get(
        (symbol or "").upper(), EarningsInfo((symbol or "").upper(), UNKNOWN,
                                             reason="empty symbol"))


def provider_health() -> dict:
    """Coverage snapshot for the health surface."""
    try:
        cur = _conn().cursor()
        cur.execute("""SELECT count(*),
                              count(next_earnings_date),
                              count(*) FILTER (WHERE next_earnings_date >= CURRENT_DATE),
                              max(earnings_updated_at)
                       FROM symbol_profiles""")
        total, with_next, future, last_upd = cur.fetchone()
        age_h = None
        if last_upd:
            age_h = (datetime.now(timezone.utc) - last_upd.astimezone(timezone.utc)).total_seconds() / 3600
        return {"ok": bool(future) and (age_h is not None and age_h < 48),
                "profiles": total, "with_next_earnings": with_next,
                "future_dated": future, "last_updated_hours": round(age_h, 1) if age_h else None,
                "writer": "scripts/earnings_enrich.py (yfinance, cron 35 6 * * 1-5)"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


if __name__ == "__main__":
    import json
    args = sys.argv[1:]
    if args:
        for s, i in sorted(get_earnings(args).items()):
            print(f"{s:8s} {i.state:15s} {i.date or '':12} src={i.source} {i.reason}")
    else:
        print(json.dumps(provider_health(), indent=1, default=str))
