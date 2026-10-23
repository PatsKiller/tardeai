"""Scan freshness for the Trade AI scanner payload (operator 2026-10-23, P1).

"These are supposed to be running like every 5 minutes … we can't have that long of a period on micro
scalps." The page used to show only the run SLOT ("0700") and the last FULL run's finish time, while the
rows themselves were refreshed by the continuous runner's LIVE cycles (trade_ai_scans.scanned_at). Nothing
told the operator how old the newest scan actually was.

Two pure functions:

* ``latest_scan_at(tickers)`` — the newest ``persisted_at`` (= trade_ai_scans.scanned_at) across the served
  rows, as an ISO string with its offset, or None. Computed once when the cache is built.
* ``scan_freshness(latest, now_utc)`` — recomputed on every serve: age in seconds, whether ``now`` is inside
  the 06:00-12:00 ET weekday scalp window, and a status. In the scalp window a scan older than
  ``STALE_AFTER_S`` (10 min: two missed 5-minute cycles) is ``STALE``; outside it the age is reported but
  never called stale (nothing is scheduled to refresh it). No timestamp → ``UNKNOWN``, never ``FRESH``.

Stdlib only. AUTHORITY: READ_ONLY_ADVISORY (presentation facts; no broker, no DB, no send).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SCALP_WINDOW_ET = ((6, 0), (12, 0))
SCALP_CADENCE_S = 300
STALE_AFTER_S = 600
CONTRACT = "ScanFreshness@v1"


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    # An unzoned stamp cannot be placed on the clock honestly; trade_ai_scans.scanned_at is timestamptz,
    # so this only drops malformed rows.
    return d if d.tzinfo is not None else None


def latest_scan_at(tickers) -> str | None:
    best: datetime | None = None
    best_raw = None
    for row in tickers or []:
        if not isinstance(row, dict):
            continue
        d = _parse(row.get("persisted_at"))
        if d is not None and (best is None or d > best):
            best, best_raw = d, row.get("persisted_at")
    return str(best_raw) if best is not None else None


def in_scalp_window(now_utc: datetime) -> bool:
    et = now_utc.astimezone(ET)
    if et.weekday() >= 5:
        return False
    m = et.hour * 60 + et.minute
    (sh, sm), (eh, em) = SCALP_WINDOW_ET
    return sh * 60 + sm <= m < eh * 60 + em


def scan_freshness(latest, now_utc: datetime | None = None) -> dict:
    now = now_utc or datetime.now(timezone.utc)
    window = in_scalp_window(now)
    d = _parse(latest)
    out = {
        "contract": CONTRACT,
        "latest_scan_at": str(latest) if d is not None else None,
        "age_sec": None,
        "scalp_window": window,
        "scalp_window_et": "06:00-12:00",
        "expected_cadence_sec": SCALP_CADENCE_S,
        "stale_after_sec": STALE_AFTER_S,
        "status": "UNKNOWN",
    }
    if d is None:
        return out
    age = max(0, round((now - d).total_seconds()))
    out["age_sec"] = age
    if not window:
        out["status"] = "OFF_WINDOW"
    else:
        out["status"] = "STALE" if age > STALE_AFTER_S else "FRESH"
    return out
