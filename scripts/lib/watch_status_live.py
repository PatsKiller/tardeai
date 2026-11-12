"""GET /api/v2/watch/status: the Watch-data verdict over exactly four required inputs (LQ-20261107-2625, Watch v003 D1).

Operator decision D1 = (b): the Watch data chip is computed over **My List, Prospects, Alerts, Regime**. Other tabs show
their own state and never turn the chip. Watch never blocks trading by itself, so this verdict is OK / STALE / UNKNOWN
only (no trade gate, no NO).

Modelled on ``lib/home_status_live.py`` and reusing its ``readonly_query`` (READ ONLY transaction, 2 s
``statement_timeout``, always rolled back): the verdict is computed on the request from STORED rows (one aggregate each,
no whole-table load, no file read, no network, no broker, no write) and cached for ``CACHE_TTL_S`` with a double-checked
lock so a poll storm costs one computation per window.

Rules (each one pinned by a test):

* An input is OK only when its store was read, has an ``as_of``, that ``as_of`` is not in the future and it is within
  the input's threshold. An unread input (no connection, query error, statement timeout, empty store, no run record) is
  UNKNOWN with a named reason, never OK and never silently STALE.
* The verdict is UNKNOWN when any required input is UNKNOWN (unknown beats wrong), else STALE when any is STALE, else OK.
  The cause names the failing inputs.
* Thresholds follow the v002 plan (W-01/W-04/W-06/W-07): My List and Prospects 30 min in regular trading hours and 26 h
  otherwise; Alerts 20 min in RTH and 26 h otherwise; Regime 26 h. If the session cannot be determined the RTH
  (stricter) limits apply and the session is reported as ``unknown``.
* Alerts has **no evaluator run record today** (``watch_alerts_eval`` is cron with no heartbeat; W-06/WV-07 adds it), so
  it reads UNKNOWN with ``needs_backend`` until ``watch_alerts_eval_runs`` exists: that table, with ``finished_at`` and
  ``status``, is the contract this module reads once the lane lands. ``watch_alerts.last_fired_at`` is not liveness and
  is not used.

Served body (the route wraps it in the api_v2 ``{"ok": true, "data": ...}`` envelope):
``{"schema": "WatchStatus@v1", "verdict", "cause", "computed_at", "session", "read_from", "required_inputs": [...ids],
"inputs": [{"id", "label", "required", "state", "source_id", "owner", "as_of", "age_s", "threshold_s", "reason",
"needs_backend", "timed_out"}]}``.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

SCHEMA = "WatchStatus@v1"
OK, STALE, UNKNOWN = "OK", "STALE", "UNKNOWN"
CACHE_TTL_S = 30
READ_FROM = "computed_on_request"
FUTURE_SKEW_S = 300

H26 = 26 * 3600
MIN30 = 30 * 60
MIN20 = 20 * 60

# id, label, source_id, owner, rth limit, off-session limit
INPUTS = (
    ("my_list", "My List", "watchlist_items", "watch curation", MIN30, H26),
    ("prospects", "Prospects", "cio_prospect", "cio", MIN30, H26),
    ("alerts", "Alerts", "watch_alerts_eval_runs", "watch alerts", MIN20, H26),
    ("regime", "Regime", "market_regime_snapshots", "market regime", H26, H26),
)
REQUIRED_INPUTS = tuple(i[0] for i in INPUTS)

_SQL = {
    "my_list": "SELECT max(updated_at) AS as_of FROM watchlist_items",
    "prospects": "SELECT max(as_of) AS as_of FROM cio_prospect",
    "regime": "SELECT max(generated_at) AS as_of FROM market_regime_snapshots",
}
_ALERTS_PRESENT = "SELECT to_regclass('public.watch_alerts_eval_runs') IS NOT NULL AS present"
_ALERTS_SQL = "SELECT max(finished_at) AS as_of FROM watch_alerts_eval_runs WHERE status IN ('ok', 'OK', 'success')"

_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


class Timeout(Exception):
    """A statement exceeded the 2 s statement_timeout (raised by ``readonly_query``)."""


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.astimezone(timezone.utc).isoformat() if d else None


def _utc(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _default_session(now: datetime) -> Optional[bool]:
    """True in regular trading hours, False outside, None when it cannot be determined."""
    try:
        from lib import cio_market_session as ms
        return bool(ms.is_rth(now))
    except Exception:  # noqa: BLE001 -- unknown session -> the stricter limits, reported as "unknown"
        return None


def _row(spec: tuple, state: str, *, reason: Optional[str] = None, as_of: Optional[datetime] = None,
         limit: Optional[int] = None, now: datetime, needs_backend: bool = False, timed_out: bool = False) -> dict[str, Any]:
    iid, label, source, owner, _r, _o = spec
    age = max(0, int((now - as_of).total_seconds())) if as_of else None
    return {"id": iid, "label": label, "required": True, "state": state, "source_id": source, "owner": owner,
            "as_of": _iso(as_of), "age_s": age, "threshold_s": limit, "reason": reason,
            "needs_backend": needs_backend, "timed_out": timed_out}


def _grade(spec: tuple, as_of: Any, limit: int, now: datetime, empty_reason: str) -> dict[str, Any]:
    d = _utc(as_of)
    if d is None:
        return _row(spec, UNKNOWN, reason=empty_reason, limit=limit, now=now)
    if d > now + timedelta(seconds=FUTURE_SKEW_S):
        return _row(spec, UNKNOWN, reason="as_of is in the future (clock or writer fault)", as_of=d, limit=limit, now=now)
    age = (now - d).total_seconds()
    if age > limit:
        return _row(spec, STALE, reason=f"last write {int(age)} s ago, limit {limit} s", as_of=d, limit=limit, now=now)
    return _row(spec, OK, as_of=d, limit=limit, now=now)


def read_input(spec: tuple, q: Callable[..., list], now: datetime, rth: Optional[bool]) -> dict[str, Any]:
    """One input as a graded row. Never raises: any failure is an UNKNOWN row with the failure named."""
    iid = spec[0]
    limit = spec[4] if rth in (True, None) else spec[5]
    try:
        if iid == "alerts":
            present = q(_ALERTS_PRESENT, None)
            if not present or not present[0].get("present"):
                return _row(spec, UNKNOWN, reason="no evaluator run record: watch_alerts_eval has no heartbeat or run table "
                            "yet (W-06 / WV-07); last_fired_at is not liveness", limit=limit, now=now, needs_backend=True)
            rows = q(_ALERTS_SQL, None)
        else:
            rows = q(_SQL[iid], None)
    except Timeout:
        return _row(spec, UNKNOWN, reason="query exceeded the 2000 ms statement timeout", limit=limit, now=now,
                    timed_out=True)
    except Exception as exc:  # noqa: BLE001 -- unread is UNKNOWN with the failure named, never OK
        return _row(spec, UNKNOWN, reason=f"read failed: {type(exc).__name__}", limit=limit, now=now)
    if not rows:
        return _row(spec, UNKNOWN, reason="the read returned no aggregate row", limit=limit, now=now)
    return _grade(spec, rows[0].get("as_of"), limit, now,
                  "the store has no rows with a timestamp" if iid != "alerts" else "no successful evaluator run recorded")


def verdict_of(inputs: list[dict[str, Any]]) -> tuple[str, str]:
    """(verdict, cause). UNKNOWN beats STALE beats OK; the cause names the inputs that decided it."""
    by = {s: [i for i in inputs if i["state"] == s] for s in (UNKNOWN, STALE, OK)}
    if len(inputs) != len(REQUIRED_INPUTS) or {i["id"] for i in inputs} != set(REQUIRED_INPUTS):
        return UNKNOWN, "required inputs missing from the computation"
    if by[UNKNOWN]:
        return UNKNOWN, "; ".join(f"{i['label']}: {i['reason']}" for i in by[UNKNOWN][:3]) + \
            (f" (+{len(by[UNKNOWN]) - 3} more)" if len(by[UNKNOWN]) > 3 else "")
    if by[STALE]:
        return STALE, "; ".join(f"{i['label']}: {i['reason']}" for i in by[STALE])
    return OK, "all four required inputs read OK within their limits"


def compute(q: Callable[..., list], now: datetime, *, session_fn: Optional[Callable[[datetime], Optional[bool]]] = None
            ) -> dict[str, Any]:
    rth = (session_fn or _default_session)(now)
    inputs = [read_input(spec, q, now, rth) for spec in INPUTS]
    verdict, cause = verdict_of(inputs)
    return {"schema": SCHEMA, "verdict": verdict, "cause": cause, "computed_at": _iso(now),
            "session": "unknown" if rth is None else ("rth" if rth else "off"), "read_from": READ_FROM,
            "required_inputs": list(REQUIRED_INPUTS), "inputs": inputs}


def _unknown(reason: str, now: datetime) -> dict[str, Any]:
    rows = [_row(spec, UNKNOWN, reason=reason, now=now) for spec in INPUTS]
    return {"schema": SCHEMA, "verdict": UNKNOWN, "cause": reason, "computed_at": _iso(now), "session": "unknown",
            "read_from": None, "required_inputs": list(REQUIRED_INPUTS), "inputs": rows}


def serve(get_conn: Callable[[], Any], *, now: Optional[datetime] = None, use_cache: bool = True,
          session_fn: Optional[Callable[[datetime], Optional[bool]]] = None) -> dict[str, Any]:
    """The body of GET /api/v2/watch/status. Computed on the request over stored rows, cached 30 s, never a 500."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if use_cache:
        hit = _CACHE.get("v")
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return {**hit[1], "cache_age_s": int(time.monotonic() - hit[0])}
    with _LOCK:
        if use_cache:  # double-checked: a waiter returns what the lock holder just computed
            hit = _CACHE.get("v")
            if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
                return {**hit[1], "cache_age_s": int(time.monotonic() - hit[0])}
        try:
            from lib.home_status_live import readonly_query
            out = compute(readonly_query(get_conn, Timeout), now, session_fn=session_fn)
        except Exception as exc:  # noqa: BLE001 -- never a 500 and never OK
            return _unknown(f"watch status read failed: {type(exc).__name__}", now)
        if use_cache:
            _CACHE["v"] = (time.monotonic(), out)
        return out
