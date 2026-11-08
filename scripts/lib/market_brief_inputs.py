"""Read-only market-data block for the market-event brief (LQ-20261107-939 part 4, design WU-1 scope).

The Sunday 20:00 ET market-event brief (`scripts/market_event_brief.py`, lane `market-event-brief`) renders the
MarketEvent@v1 payload from ``lib.market_event_api.build_active``: episode, market gate, candidates, accounts. It
carried NO market data at all -- no futures, no cash indices, no movers, no sectors, no international exposure --
so the weekly outlook had to be assembled by hand. This module supplies that block and nothing else.

It is a READER. Four independent sections, each read with the caller's read-only ``db_query(sql, params)``:

* ``quotes``        - the newest stored off-hours row per futures root and cash index (``market_quotes_extended``,
                      feed from config). A cash index's carried level is reported with the print it came from, never
                      as a fresh print (``reference_basis`` names the print's ET date; ``bar_end`` is the night
                      anchor). ``session`` is the row's own session, so a row from Friday is never shown as Sunday's.
* ``movers``        - the newest ``market_movers`` snapshot: top gainers and top losers for the freshest capture.
* ``sectors``       - the newest ``sector_rs_daily`` relative strength, joined to each ETF's OWN newest
                      ``sector_momentum_state`` row (with that row's ``as_of``, so an older state is dated, not
                      passed off as the RS day's).
* ``international`` - the newest quote per international ETF (``market_quotes``), labelled as an ETF, never as an
                      index level.

Honesty rules (the brief is an operator surface):
* A section whose read FAILED is ``state: "unavailable"`` with the reason. It is never an empty list dressed up as
  "nothing to report", and never a zero.
* Every section states its own ``as_of``. The brief is rendered at 20:00 ET on Sunday while the off-hours lane fires
  on the same quarter hour, so the newest row may be Friday's; the renderer prints the as-of, and a stale section
  says so.
* ``quote`` rows are levels and moves of market data only. MBI_BEHAVIOR = 0: no order, stop, broker or write path.

Hermetic: no imports beyond the standard library, no network, no DB handle of its own, no scheduler.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

SCHEMA = "MarketBriefData@v1"
DbQuery = Callable[..., Any]

FUTURES_ROOTS: tuple[str, ...] = ("/ES", "/NQ", "/YM", "/RTY")
CASH_INDICES: tuple[str, ...] = ("$SPX", "$COMPX", "$DJI", "$RUT", "$NDX")
SECTOR_ETFS: tuple[str, ...] = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
# US-listed proxies for the foreign sessions a cash-index feed does not cover here (WU-7 owns real index levels).
# LQ-20261107-972 (design WU-7, operator decision D3): the Europe proxies EWG EWU EZU VGK join the Asia and EM ones,
# so tonight's fallback covers the European close as well as Asia. Every row is labelled `basis: etf_derived` — an ETF
# proxy is not an index level, and is never passed off as one; a proxy with no quote is NAMED in `missing`, never zero.
INTERNATIONAL_ETFS: tuple[str, ...] = ("EWJ", "EFA", "EEM", "FXI", "INDA", "EWZ", "EWG", "EWU", "EZU", "VGK")

MOVERS_SIGNALS: tuple[str, ...] = ("top_gainers", "top_losers")
MOVERS_LIMIT = 5
LOOKBACK_DAYS = 14  # bounded reads: a section with nothing inside this window reports its own as_of, never "today"


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = _iso(v)
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _rows(db_query: DbQuery, sql: str, params: Any = None) -> Optional[list[dict[str, Any]]]:
    """None = the read failed (table missing, DB down); [] = read fine, no rows. The two are never conflated."""
    try:
        r = db_query(sql, params)
    except Exception:  # noqa: BLE001 — a failed read is "unavailable", never an empty section
        return None
    if r is None:
        return None
    return [dict(x) for x in r]


def _section(*, as_of: Any, rows: Sequence[Mapping[str, Any]], note: Optional[str] = None,
             unavailable: Optional[str] = None) -> dict[str, Any]:
    if unavailable is not None:
        return {"state": "unavailable", "as_of": None, "rows": [], "note": unavailable}
    out: dict[str, Any] = {"state": "ok" if rows else "empty", "as_of": _iso(as_of), "rows": list(rows)}
    if note:
        out["note"] = note
    return out


# --------------------------------------------------------------------------- sections


QUOTES_SQL = (
    "SELECT DISTINCT ON (symbol) symbol, session, session_date, bar_end, price, reference_close, reference_date, "
    "change_pct, reference_basis FROM market_quotes_extended "
    "WHERE feed = %s AND symbol = ANY(%s) AND bar_end >= %s ORDER BY symbol, bar_end DESC"
)


def quotes(db_query: DbQuery, *, feed: str, now: datetime) -> dict[str, Any]:
    """Newest stored row per futures root and cash index, in a stable display order."""
    symbols = [*FUTURES_ROOTS, *CASH_INDICES]
    got = _rows(db_query, QUOTES_SQL, [feed, symbols, (now - timedelta(days=LOOKBACK_DAYS)).isoformat()])
    if got is None:
        return _section(as_of=None, rows=[], unavailable=f"market_quotes_extended unreadable (feed {feed})")
    by = {str(r.get("symbol") or "").upper(): r for r in got}
    order = {s: i for i, s in enumerate(symbols)}
    rows = []
    for sym in sorted(by, key=lambda s: order.get(s, len(order))):
        r = by[sym]
        end = _dt(r.get("bar_end"))
        rows.append({
            "symbol": sym,
            "session": r.get("session"),
            "session_date": _iso(r.get("session_date")),
            "as_of": _iso(r.get("bar_end")),
            "age_hours": round((now - end).total_seconds() / 3600.0, 1) if end else None,
            "price": _num(r.get("price")),
            "reference_close": _num(r.get("reference_close")),
            "reference_date": _iso(r.get("reference_date")),
            "change_pct": _num(r.get("change_pct")),
            "reference_basis": r.get("reference_basis"),
            # A level-only row has no measured move; the basis says why (a carried cash-index print names its date).
            "level_only": r.get("reference_close") is None,
        })
    newest = max((_dt(r.get("bar_end")) for r in got if r.get("bar_end") is not None), default=None)
    sec = _section(as_of=newest, rows=rows,
                   note=None if rows else f"no stored {feed} off-hours row in the last {LOOKBACK_DAYS} days")
    # A configured instrument with no stored row is named, never silently absent: an unquoted symbol and a zero are
    # different claims, and only one of them is true.
    sec["missing"] = [s for s in symbols if s not in by]
    return sec


MOVERS_STAMP_SQL = "SELECT signal, max(captured_at) AS at FROM market_movers WHERE signal = ANY(%s) GROUP BY signal"
MOVERS_SQL = (
    "SELECT signal, symbol, company, sector, last, change_pct, volume, captured_at FROM market_movers "
    "WHERE signal = %s AND captured_at = %s ORDER BY change_pct {direction} LIMIT %s"
)


def movers(db_query: DbQuery, *, now: datetime) -> dict[str, Any]:
    """Top gainers and top losers of the freshest snapshot (one capture per signal, ordered by change)."""
    stamps = _rows(db_query, MOVERS_STAMP_SQL, [list(MOVERS_SIGNALS)])
    if stamps is None:
        return _section(as_of=None, rows=[], unavailable="market_movers unreadable")
    newest: Optional[datetime] = None
    out: list[dict[str, Any]] = []
    for signal in MOVERS_SIGNALS:
        at = next((_dt(s.get("at")) for s in stamps if str(s.get("signal")) == signal), None)
        if at is None:
            continue
        newest = at if newest is None or at > newest else newest
        got = _rows(db_query, MOVERS_SQL.format(direction="DESC" if signal == "top_gainers" else "ASC"),
                    [signal, at, MOVERS_LIMIT])
        if got is None:
            return _section(as_of=None, rows=[], unavailable=f"market_movers unreadable ({signal})")
        for r in got:
            out.append({"signal": signal, "symbol": r.get("symbol"), "company": r.get("company"),
                        "sector": r.get("sector"), "last": _num(r.get("last")),
                        "change_pct": _num(r.get("change_pct")), "volume": r.get("volume"),
                        "captured_at": _iso(r.get("captured_at"))})
    return _section(as_of=newest, rows=out, note=None if out else "no market_movers snapshot in the table")


SECTORS_SQL = (
    "SELECT s.symbol AS etf, s.rs_date, s.rs, s.close, m.as_of AS state_as_of, m.sector, m.state, m.rs5, m.rs20 "
    "FROM sector_rs_daily s "
    "LEFT JOIN sector_momentum_state m ON m.etf = s.symbol "
    " AND m.as_of = (SELECT max(as_of) FROM sector_momentum_state m2 WHERE m2.etf = s.symbol) "
    "WHERE s.rs_date = (SELECT max(rs_date) FROM sector_rs_daily) AND s.symbol = ANY(%s) "
    "ORDER BY s.rs DESC NULLS LAST"
)


def sectors(db_query: DbQuery) -> dict[str, Any]:
    """Newest relative strength per sector ETF, with that ETF's own newest momentum state when one exists.

    The state is joined per ETF on ITS newest ``as_of``, not the table's: on 2026-11-06 the table held only the two
    STYLE rows, so a join on ``max(as_of)`` would have shown no state for any sector. Each row reports its own
    ``state_as_of`` so a state from an earlier session is never presented as the RS day's.
    """
    got = _rows(db_query, SECTORS_SQL, [list(SECTOR_ETFS)])
    if got is None:
        return _section(as_of=None, rows=[], unavailable="sector_rs_daily / sector_momentum_state unreadable")
    rows = [{"etf": r.get("etf"), "sector": r.get("sector"), "rs": _num(r.get("rs")), "close": _num(r.get("close")),
             "state": r.get("state"), "state_as_of": _iso(r.get("state_as_of")),
             "rs5": _num(r.get("rs5")), "rs20": _num(r.get("rs20"))} for r in got]
    as_of = max((_iso(r.get("rs_date")) or "" for r in got), default=None) or None
    return _section(as_of=as_of, rows=rows, note=None if rows else "no sector_rs_daily row for the newest date")


INTL_SQL = (
    "SELECT DISTINCT ON (symbol) symbol, source, price, day_change_pct, fetched_at FROM market_quotes "
    "WHERE symbol = ANY(%s) AND price > 0 AND fetched_at >= %s ORDER BY symbol, fetched_at DESC"
)


def international(db_query: DbQuery, *, now: datetime) -> dict[str, Any]:
    """Newest quote per international ETF: an ETF proxy for a foreign session, labelled as such."""
    got = _rows(db_query, INTL_SQL, [list(INTERNATIONAL_ETFS), (now - timedelta(days=LOOKBACK_DAYS)).isoformat()])
    if got is None:
        return _section(as_of=None, rows=[], unavailable="market_quotes unreadable")
    order = {s: i for i, s in enumerate(INTERNATIONAL_ETFS)}
    rows = []
    for r in sorted(got, key=lambda x: order.get(str(x.get("symbol") or "").upper(), len(order))):
        at = _dt(r.get("fetched_at"))
        rows.append({"symbol": str(r.get("symbol") or "").upper(), "basis": "etf_derived", "source": r.get("source"),
                     "price": _num(r.get("price")), "change_pct": _num(r.get("day_change_pct")),
                     "as_of": _iso(r.get("fetched_at")),
                     "age_hours": round((now - at).total_seconds() / 3600.0, 1) if at else None})
    newest = max((_dt(r.get("fetched_at")) for r in got if r.get("fetched_at") is not None), default=None)
    sec = _section(as_of=newest, rows=rows,
                   note=None if rows else f"no international ETF quote in the last {LOOKBACK_DAYS} days")
    # INDA and EWZ legitimately go days without a quote row; a proxy that was not read is named, never dropped.
    seen = {str(r.get("symbol") or "").upper() for r in got}
    sec["missing"] = [s for s in INTERNATIONAL_ETFS if s not in seen]
    return sec


def gather(db_query: DbQuery, *, feed: str = "schwab", now: Optional[datetime] = None) -> dict[str, Any]:
    """All four sections. One failed read never hides another: each section states its own state and reason."""
    now = now or datetime.now(timezone.utc)
    return {
        "schema": SCHEMA,
        "computed_at": now.isoformat(),
        "quotes": quotes(db_query, feed=feed, now=now),
        "movers": movers(db_query, now=now),
        "sectors": sectors(db_query),
        "international": international(db_query, now=now),
    }
