"""Session Close — Data Broker read model: the close of each NYSE session, taken only after the bell.

LQ-20261107-275 (old LQ-126). ``daily_close_cache`` was filled with "the last quote of each New York
calendar day" from ``market_quotes``. That is not a close:

* the quote poller keeps running after the bell, so the last quote of a session day is an
  after-hours trade (XLK 2026-11-05: last quote 161.75 at 16:45 ET, official close 162.45);
* before LQ-126 the pick was arbitrary, so it was often the 07:15 pre-market print, whose ``price``
  is still the previous evening's after-hours trade: the cache was shifted one session
  (PWR cached 2026-11-04/05/06 = the true closes of 11-03/04/05);
* yfinance rows and weekend rows also landed in the cache (PWR "2026-11-07", a Saturday, from a
  yfinance 09:10 quote), and the grader built its session calendar from those cached dates.

What this projection returns, per (symbol, session_date), using only rows fetched after that
session's official close (``cio_market_session``: 16:00 ET, 13:00 ET on early-close days):

1. ``next_session_prev_close`` (preferred). The first quote fetched on the next trading day, from
   04:00 ET until that day's close, carries ``prev_close``: the exchange's official close of the
   session. Measured 2026-11-07 over five sessions: within a day ``prev_close`` never changes
   (0 of ~27,600 symbol-days), and it equals the 16:00:0x print within 5 bp for 99.4% of symbols.
2. ``post_close_quote`` (provisional, for the newest session). The first quote fetched in
   [official close, official close + 5 min). It is replaced by (1) when the next session opens.
3. Nothing otherwise. An intraday, after-hours or pre-market ``price`` is never returned as a close.

Sources: ``alpaca`` and ``finviz`` only. yfinance is excluded (operator rule: Finviz, never yfinance).

Zero provider calls. Read-only. ``session_close_sql`` is also the SELECT the outcome grader's
cache refresh inserts from, so the reader and the writer cannot disagree about what a close is.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from lib.cio_market_session import NYSESessionService, PREMARKET_START, get_session_service
from lib.data_broker.envelope import envelope

DOMAIN = "quote_price"
PROJECTION = "session_close"
TABLE = "market_quotes"

#: quote sources a close may come from. yfinance is never one of them.
SOURCES: tuple[str, ...] = ("alpaca", "finviz")
METHOD_OFFICIAL = "next_session_prev_close"
METHOD_POST_CLOSE = "post_close_quote"
METHODS: tuple[str, ...] = (METHOD_OFFICIAL, METHOD_POST_CLOSE)
#: how long after the bell a print still counts as the closing print
POST_CLOSE_GRACE_SECONDS = 300
#: longest run of non-trading days between two sessions (a long weekend plus a holiday is 4)
_MAX_GAP_DAYS = 10


@dataclass(frozen=True)
class Session:
    session_date: date
    close_at: datetime      # official close, exchange tz (13:00 on early-close days)
    next_date: date         # the next trading day
    next_from: datetime     # 04:00 ET on next_date: the earliest quote whose prev_close is this close
    next_until: datetime    # the next session's official close


def _next_trading_day(d: date, svc: NYSESessionService) -> date:
    for k in range(1, _MAX_GAP_DAYS + 1):
        nd = d + timedelta(days=k)
        if svc.is_trading_day(nd):
            return nd
    raise ValueError(f"no trading day within {_MAX_GAP_DAYS} days after {d}")


def sessions_between(start: date, end: date, *, service: Optional[NYSESessionService] = None) -> list[Session]:
    """Every NYSE session with start <= session_date <= end; weekends and holidays are not sessions."""
    svc = service or get_session_service()
    out: list[Session] = []
    d = start
    while d <= end:
        if svc.is_trading_day(d):
            _, close_at, _ = svc.official_bounds(d)
            nd = _next_trading_day(d, svc)
            _, next_close, _ = svc.official_bounds(nd)
            out.append(Session(d, close_at, nd, datetime.combine(nd, PREMARKET_START, tzinfo=svc.tz), next_close))
        d += timedelta(days=1)
    return out


_SQL = """WITH s AS (
  SELECT * FROM unnest(%(session_date)s::date[], %(close_at)s::timestamptz[], %(next_date)s::date[],
                       %(next_from)s::timestamptz[], %(next_until)s::timestamptz[])
         AS s(session_date, close_at, next_date, next_from, next_until)
), q AS (
  SELECT UPPER(market_quotes.symbol) AS symbol, market_quotes.price, market_quotes.prev_close,
         market_quotes.fetched_at AS quote_at, market_quotes.id AS quote_id,
         (market_quotes.fetched_at AT TIME ZONE 'America/New_York')::date AS ny_date
  FROM market_quotes
  WHERE market_quotes.fetched_at >= %(lo)s AND market_quotes.fetched_at < %(hi)s
    AND market_quotes.source = ANY(%(sources)s){symbol_filter}
), official AS (
  SELECT DISTINCT ON (q.symbol, s.session_date)
         q.symbol, s.session_date, q.prev_close AS close_price, 'next_session_prev_close'::text AS method,
         q.quote_at
  FROM q JOIN s ON q.ny_date = s.next_date
  WHERE q.quote_at >= s.next_from AND q.quote_at < s.next_until AND q.quote_at > s.close_at
    AND q.prev_close IS NOT NULL AND q.prev_close > 0
  ORDER BY q.symbol, s.session_date, q.quote_at ASC, q.quote_id ASC
), post_close AS (
  SELECT DISTINCT ON (q.symbol, s.session_date)
         q.symbol, s.session_date, q.price AS close_price, 'post_close_quote'::text AS method, q.quote_at
  FROM q JOIN s ON q.ny_date = s.session_date
  WHERE q.quote_at >= s.close_at AND q.quote_at < s.close_at + make_interval(secs => %(grace)s)
    AND q.price IS NOT NULL AND q.price > 0
  ORDER BY q.symbol, s.session_date, q.quote_at ASC, q.quote_id ASC
)
SELECT COALESCE(o.symbol, p.symbol) AS symbol,
       COALESCE(o.session_date, p.session_date) AS session_date,
       COALESCE(o.close_price, p.close_price) AS close_price,
       COALESCE(o.method, p.method) AS method,
       COALESCE(o.quote_at, p.quote_at) AS quote_at
FROM official o
FULL OUTER JOIN post_close p ON p.symbol = o.symbol AND p.session_date = o.session_date"""


def session_close_sql(*, with_symbols: bool = False) -> str:
    """The SELECT (symbol, session_date, close_price, method, quote_at); named %(...)s params."""
    flt = "\n    AND market_quotes.symbol = ANY(%(symbols)s)" if with_symbols else ""
    return _SQL.replace("{symbol_filter}", flt)


def session_close_params(sessions: list[Session], *, symbols: Optional[Iterable[str]] = None,
                         sources: Iterable[str] = SOURCES,
                         grace_seconds: int = POST_CLOSE_GRACE_SECONDS) -> dict[str, Any]:
    if not sessions:
        raise ValueError("no sessions")
    srcs = [str(s) for s in sources]
    if any(s.lower() == "yfinance" for s in srcs):
        raise ValueError("yfinance is never a close source")
    params: dict[str, Any] = {
        "session_date": [s.session_date for s in sessions],
        "close_at": [s.close_at for s in sessions],
        "next_date": [s.next_date for s in sessions],
        "next_from": [s.next_from for s in sessions],
        "next_until": [s.next_until for s in sessions],
        "lo": min(s.close_at for s in sessions),
        "hi": max(s.next_until for s in sessions),
        "sources": srcs,
        "grace": int(grace_seconds),
    }
    if symbols is not None:
        params["symbols"] = sorted({str(x).upper().strip() for x in symbols if str(x).strip()})
    return params


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def get_session_closes(db_query, start: date, end: date, *, symbols: Optional[Iterable[str]] = None,
                       service: Optional[NYSESessionService] = None, now=None, registry=None) -> dict[str, Any]:
    """{ok, closes: [{symbol, session_date, close, method, quote_at}], <envelope>}; never fetches."""
    sessions = sessions_between(start, end, service=service)
    rows: list[dict[str, Any]] = []
    error = None
    if sessions:
        sym_list = None if symbols is None else list(symbols)
        try:
            rows = db_query(session_close_sql(with_symbols=sym_list is not None),
                            session_close_params(sessions, symbols=sym_list), fetch="all") or []
        except Exception as e:  # noqa: BLE001
            error = str(e)[:200]
    closes = []
    for r in rows:
        sd, qa = r.get("session_date"), r.get("quote_at")
        closes.append({"symbol": r.get("symbol"),
                       "session_date": sd.isoformat() if hasattr(sd, "isoformat") else sd,
                       "close": _f(r.get("close_price")), "method": r.get("method"),
                       "quote_at": qa.isoformat() if hasattr(qa, "isoformat") else qa})
    as_of = max((r.get("quote_at") for r in rows if r.get("quote_at")), default=None)
    env = envelope(DOMAIN, as_of, now=now, registry=registry,
                   source={"table": TABLE, "projection": PROJECTION, "sources": list(SOURCES)})
    out = {"ok": error is None, "closes": closes, "n": len(closes),
           "sessions": [s.session_date.isoformat() for s in sessions], "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out


__all__ = ["DOMAIN", "PROJECTION", "SOURCES", "METHODS", "METHOD_OFFICIAL", "METHOD_POST_CLOSE",
           "POST_CLOSE_GRACE_SECONDS", "Session", "sessions_between", "session_close_sql",
           "session_close_params", "get_session_closes"]

