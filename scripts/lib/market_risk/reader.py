"""Production read side of the Market Risk Engine: ``PgReader`` implements ``contract.DataReader``.

Reads only EXISTING stores (DSN-20261031-market-risk-engine P1; new stores wait for their §7A rows):
``market_quotes``, ``market_ohlcv_bars``, ``market_regime_indicators``, ``fred_economic_series``,
``option_chain_snapshots``, ``sector_momentum_state``, ``symbol_profiles`` and the macro calendar
(``<state root>/data/runtime/macro_calendar.json`` when the refresh lane has written it, else the operator's
``config/macro_calendar_overrides.json``).

Rules every method keeps:

* **As-of correct.** Nothing observed after ``end`` is returned, so replay at a historical instant sees only what
  existed then (a row's ``created_at``/``fetched_at`` must be ``<= end``, not just its business date).
* **Every row carries ``as_of``** (ISO-8601) and ``source``.
* **Read-only.** The session is set ``default_transaction_read_only``; the reader never writes.
* **No portfolio data.** ``sector_momentum_state.book_pct``/``book_dollars`` are not returned (exposure belongs to
  the exposure module, which reads positions through the positions projection).

Daily closes: ``market_ohlcv_bars`` (``timeframe='daily'``) covers few index ETFs and stopped updating for some
(SPY's last daily bar is 2026-10-09 as of 2026-10-31), so ``daily_bars`` merges it with closes derived from the
Alpaca quote snapshots in ``market_quotes``: the close of session D is the ``prev_close`` carried by the first quote
of the next session; the newest session's close is its last regular-hours quote, flagged ``provisional``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OVERRIDES_PATH = PROJECT_ROOT / "config" / "macro_calendar_overrides.json"
REGULAR_CLOSE_CUTOFF_ET = time(16, 0, 59)  # last quote at or before this = the newest session's provisional close
VIX_SYMBOL = "^VIX"
DAILY_TIMEFRAME = "daily"
QUOTE_SOURCE_FOR_CLOSES = "alpaca"
SECTOR_COLUMNS = (
    "as_of",
    "etf",
    "sector",
    "state",
    "rs5",
    "rs20",
    "rs60",
    "slope",
    "breadth_pct",
    "breadth_n",
    "hermes_pulse",
    "hermes_delta",
    "news_negatives",
    "top_negative",
    "created_at",
)


def _num(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("market-risk reader needs a timezone-aware instant")
    return dt


def _close_instant(d: date) -> datetime:
    return datetime.combine(d, time(16, 0), ET)


def _default_conn():
    try:
        from scripts.session13_db import get_conn
    except ImportError:  # scripts/ on sys.path
        from session13_db import get_conn  # type: ignore[no-redef]
    return get_conn()


class PgReader:
    """``DataReader`` over Postgres. ``conn_factory`` returns a DB-API connection (default: session13_db)."""

    def __init__(
        self,
        conn_factory: Callable[[], Any] | None = None,
        *,
        publication_lag_days: int = 1,
        backfill_grace_days: int = 14,
    ):
        self._factory = conn_factory or _default_conn
        self._conn = None
        self.publication_lag_days = publication_lag_days
        # A FRED row is knowable at ``end`` when it was first fetched by then, or when its observation is so old that
        # it was published before ``end`` even if a later backfill fetched it (review of #2362, M1).
        self.backfill_grace_days = backfill_grace_days
        self.macro_calendar_note = ""

    # -- plumbing ---------------------------------------------------------------------------------------------
    def _cur(self):
        if self._conn is None:
            conn = self._factory()
            # Read-only from the FIRST statement. ``SET default_transaction_read_only`` only affects transactions that
            # start after it, and the reader never commits, so its first transaction stayed read-write (data-feed
            # review of #2383). ``set_session(readonly=True)`` (psycopg2) or ``read_only`` (psycopg 3) applies before
            # the first transaction begins; a connection exposing neither is refused rather than used read-write.
            if hasattr(conn, "set_session"):
                conn.set_session(readonly=True)
            elif hasattr(conn, "read_only"):
                conn.read_only = True
            else:
                conn.close()
                raise RuntimeError("market_risk reader: connection cannot be made read-only; refusing to use it")
            self._conn = conn
        return self._conn.cursor()

    def _rows(self, sql: str, params: Iterable[Any]) -> list[dict[str, Any]]:
        cur = self._cur()
        try:
            cur.execute(sql, list(params))
            names = [c[0] for c in cur.description]
            return [{k: _num(v) for k, v in zip(names, r)} for r in cur.fetchall()]
        finally:
            cur.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- DataReader -------------------------------------------------------------------------------------------
    def quotes(self, symbols: Iterable[str], *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT symbol, source, price, prev_close, day_change_pct, volume, fetched_at FROM market_quotes "
            "WHERE symbol = ANY(%s) AND fetched_at >= %s AND fetched_at <= %s ORDER BY symbol, fetched_at",
            [list(symbols), _aware(start), _aware(end)],
        )
        for r in rows:
            r["as_of"] = _iso(r["fetched_at"])
            r["fetched_at"] = r["as_of"]
        return rows

    def daily_bars(self, symbols: Iterable[str], *, sessions: int, end: datetime) -> list[dict[str, Any]]:
        syms = [s.upper() for s in symbols]
        end = _aware(end)
        out: dict[tuple[str, date], dict[str, Any]] = {}
        for r in self._rows(
            "SELECT symbol, bar_time, open, high, low, close, volume, source, created_at FROM market_ohlcv_bars "
            "WHERE timeframe = %s AND symbol = ANY(%s) AND bar_time <= %s "
            "AND (created_at IS NULL OR created_at <= %s) ORDER BY symbol, bar_time",
            [DAILY_TIMEFRAME, syms, end, end],
        ):
            d = r["bar_time"].astimezone(ET).date() if isinstance(r["bar_time"], datetime) else r["bar_time"]
            if _close_instant(d) > end:
                continue  # the bar for a session still in progress at `end` did not exist yet
            out[(r["symbol"], d)] = {
                "symbol": r["symbol"],
                "date": d.isoformat(),
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"],
                "source": f"market_ohlcv_bars:{r['source']}",
                "provisional": False,
                "as_of": _iso(_close_instant(d)),
            }
        span = timedelta(days=int(sessions * 1.6) + 10)
        for row in self._quote_closes(syms, start=end - span, end=end):
            out.setdefault((row["symbol"], date.fromisoformat(row["date"])), row)
        if VIX_SYMBOL in syms:
            for row in self._vix_closes(start=end - span, end=end):
                out.setdefault((VIX_SYMBOL, date.fromisoformat(row["date"])), row)
        by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (sym, _d), row in sorted(out.items()):
            by_sym[sym].append(row)
        return [r for sym in sorted(by_sym) for r in by_sym[sym][-int(sessions) :]]

    def session_opens(self, symbols: Iterable[str], *, sessions: int, end: datetime) -> list[dict[str, Any]]:
        """Regular-session opening prints from ``market_ohlcv_bars`` (daily), each knowable from 09:30 ET of its session
        and only if the row existed by ``end``. Only ``open`` is returned: the rest of an in-progress bar is unknowable."""
        syms = [s.upper() for s in symbols]
        end = _aware(end)
        out: dict[tuple[str, date], dict[str, Any]] = {}
        for r in self._rows(
            "SELECT symbol, bar_time, open, created_at FROM market_ohlcv_bars "
            "WHERE timeframe = %s AND symbol = ANY(%s) AND bar_time <= %s AND open IS NOT NULL "
            "AND (created_at IS NULL OR created_at <= %s) ORDER BY symbol, bar_time",
            [DAILY_TIMEFRAME, syms, end, end],
        ):
            d = r["bar_time"].astimezone(ET).date() if isinstance(r["bar_time"], datetime) else r["bar_time"]
            t = datetime.combine(d, time(9, 30), tzinfo=ET)
            if t > end:
                continue
            out[(r["symbol"], d)] = {"symbol": r["symbol"], "date": d.isoformat(), "open": r["open"], "as_of": _iso(t)}
        by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (sym, _d), row in sorted(out.items()):
            by_sym[sym].append(row)
        return [r for sym in sorted(by_sym) for r in by_sym[sym][-int(sessions) :]]

    def _vix_closes(self, *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """VIX daily closes when no ^VIX bars exist: FRED VIXCLS (the official close, published with a lag; ``fred``
        applies it) first, then — only for days FRED has not published yet — the regime collector's ``vix_close``,
        which is a 16:05 ET snapshot taken BEFORE the 16:15 settlement and is labelled as such (review of #2362, B6:
        10-29 snapshot 16.59 vs VIXCLS 17.20). Same shape as a bar."""
        rows = self._rows(
            "SELECT DISTINCT ON ((created_at AT TIME ZONE 'America/New_York')::date) "
            "(created_at AT TIME ZONE 'America/New_York')::date AS d, value, created_at "
            "FROM market_regime_indicators WHERE indicator_key = 'vix_close' AND value IS NOT NULL "
            "AND created_at >= %s AND created_at <= %s "
            "AND (created_at AT TIME ZONE 'America/New_York')::time >= %s "
            "ORDER BY (created_at AT TIME ZONE 'America/New_York')::date, created_at DESC",
            [start, end, REGULAR_CLOSE_CUTOFF_ET],
        )
        out = {
            r["d"]: {
                "symbol": VIX_SYMBOL,
                "date": r["d"].isoformat(),
                "open": None,
                "high": None,
                "low": None,
                "close": r["value"],
                "volume": None,
                "source": "market_regime_indicators:vix_close_1605_snapshot",
                "provisional": True,
                "as_of": _iso(r["created_at"]),
            }
            for r in rows
        }
        for f in self.fred(["VIXCLS"], observations=400, end=end):
            d = date.fromisoformat(str(f["observation_date"])[:10])
            if d >= _aware(start).astimezone(ET).date() and f.get("value") is not None:
                out[d] = {  # the official close replaces any pre-settlement snapshot for the same day
                    "symbol": VIX_SYMBOL,
                    "date": d.isoformat(),
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": f["value"],
                    "volume": None,
                    "source": "fred_economic_series:VIXCLS",
                    "provisional": False,
                    "as_of": _iso(_close_instant(d)),
                }
        return [out[d] for d in sorted(out)]

    def _quote_closes(self, symbols: list[str], *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT symbol, price, prev_close, fetched_at FROM market_quotes WHERE source = %s AND symbol = ANY(%s) "
            "AND fetched_at >= %s AND fetched_at <= %s ORDER BY symbol, fetched_at",
            [QUOTE_SOURCE_FOR_CLOSES, symbols, start, end],
        )
        days: dict[str, dict[date, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for r in rows:
            ts = r["fetched_at"]
            days[r["symbol"]][ts.astimezone(ET).date()].append(r)
        out: list[dict[str, Any]] = []
        for sym, by_day in days.items():
            ordered = sorted(by_day)
            for i, d in enumerate(ordered):
                if i + 1 < len(ordered):
                    nxt = by_day[ordered[i + 1]][0]
                    if nxt.get("prev_close") is None:
                        continue
                    close, prov, seen = nxt["prev_close"], False, nxt["fetched_at"]
                else:
                    regular = [q for q in by_day[d] if q["fetched_at"].astimezone(ET).time() <= REGULAR_CLOSE_CUTOFF_ET]
                    if not regular or regular[-1].get("price") is None:
                        continue
                    close, seen = regular[-1]["price"], regular[-1]["fetched_at"]
                    prov = True  # replaced by the next session's prev_close once that session has a quote
                out.append(
                    {
                        "symbol": sym,
                        "date": d.isoformat(),
                        "open": None,
                        "high": None,
                        "low": None,
                        "close": close,
                        "volume": None,
                        "source": "market_quotes:alpaca_prev_close" if not prov else "market_quotes:alpaca_last",
                        "provisional": prov,
                        "as_of": _iso(seen),
                    }
                )
        return out

    def regime_indicators(self, *, end: datetime) -> list[dict[str, Any]]:
        snap = self._rows(
            "SELECT snapshot_id FROM market_regime_indicators WHERE created_at <= %s ORDER BY created_at DESC LIMIT 1",
            [_aware(end)],
        )
        if not snap:
            return []
        rows = self._rows(
            "SELECT snapshot_id, indicator_key, indicator_group, value, value_text, signal, source_key, payload, "
            "created_at FROM market_regime_indicators WHERE snapshot_id = %s AND created_at <= %s ORDER BY indicator_key",
            [snap[0]["snapshot_id"], end],
        )
        for r in rows:
            r["as_of"] = _iso(r.pop("created_at"))
            r["source"] = f"market_regime_indicators:{r.get('source_key')}"
        return rows

    def fred(self, series: Iterable[str], *, observations: int, end: datetime) -> list[dict[str, Any]]:
        last_known = (_aware(end).astimezone(ET).date()) - timedelta(days=self.publication_lag_days)
        rows = self._rows(
            "SELECT series_id, series_name, value, observation_date, fetched_at FROM ("
            " SELECT *, row_number() OVER (PARTITION BY series_id ORDER BY observation_date DESC) rn"
            " FROM fred_economic_series WHERE series_id = ANY(%s) AND observation_date <= %s"
            " AND (fetched_at <= %s OR observation_date <= %s)) t "
            "WHERE rn <= %s ORDER BY series_id, observation_date",
            [
                list(series),
                last_known,
                _aware(end),
                last_known - timedelta(days=int(self.backfill_grace_days)),
                int(observations),
            ],
        )
        for r in rows:
            r["as_of"] = _iso(r["observation_date"])
            r["observation_date"] = r["as_of"]
            r["fetched_at"] = _iso(r["fetched_at"])
            r["source"] = f"fred_economic_series:{r['series_id']}"
        return rows

    def option_snapshots(self, symbols: Iterable[str], *, sessions: int, end: datetime) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT * FROM (SELECT as_of, symbol, put_oi, call_oi, put_vol, call_vol, pc_oi_ratio, pc_vol_ratio, "
            " atm_iv, skew25, underlying_price, created_at,"
            " row_number() OVER (PARTITION BY symbol ORDER BY as_of DESC) rn FROM option_chain_snapshots"
            " WHERE symbol = ANY(%s) AND as_of <= %s AND created_at <= %s) t WHERE rn <= %s ORDER BY symbol, as_of",
            [list(symbols), _aware(end).astimezone(ET).date(), end, int(sessions)],
        )
        for r in rows:
            r.pop("rn", None)
            r["session_date"] = _iso(r["as_of"])
            r["as_of"] = _iso(r.pop("created_at"))
            r["source"] = "option_chain_snapshots"
        return rows

    def sector_states(self, *, end: datetime) -> list[dict[str, Any]]:
        cols = ", ".join(SECTOR_COLUMNS)
        rows = self._rows(
            f"SELECT DISTINCT ON (etf) {cols} FROM sector_momentum_state WHERE as_of <= %s AND created_at <= %s "
            "ORDER BY etf, as_of DESC, created_at DESC",
            [_aware(end).astimezone(ET).date(), end],
        )
        for r in rows:
            r["session_date"] = _iso(r["as_of"])
            r["as_of"] = _iso(r.pop("created_at"))
            r["source"] = "sector_momentum_state"
        return rows

    def earnings_calendar(self, *, start: datetime, end: datetime, now: datetime | None = None) -> list[dict[str, Any]]:
        """Earnings rows in [start, end] that were KNOWN at ``now`` (``earnings_updated_at <= now``). ``end`` is the
        forward window, not the evaluation instant (review of #2362, M1); live callers may omit ``now``."""
        d0, d1 = _aware(start).astimezone(ET).date(), _aware(end).astimezone(ET).date()
        known_at = _aware(now) if now is not None else datetime.now(timezone.utc)
        rows = self._rows(
            "SELECT symbol, sector, industry, instrument_type, next_earnings_date, last_earnings_date, "
            "earnings_updated_at FROM symbol_profiles WHERE (next_earnings_date BETWEEN %s AND %s "
            "OR last_earnings_date BETWEEN %s AND %s) AND earnings_updated_at <= %s ORDER BY symbol",
            [d0, d1, d0, d1, known_at],
        )
        out = []
        for r in rows:
            for kind in ("next_earnings_date", "last_earnings_date"):
                d = r.get(kind)
                if d is not None and d0 <= d <= d1:
                    out.append(
                        {
                            "symbol": r["symbol"],
                            "date": d.isoformat(),
                            "kind": kind.split("_")[0],
                            "sector": r.get("sector"),
                            "industry": r.get("industry"),
                            "instrument_type": r.get("instrument_type"),
                            "as_of": _iso(r.get("earnings_updated_at")),
                            "source": "symbol_profiles",
                        }
                    )
        return out

    def index_weights(
        self, *, end: datetime, lookback_days: int = 30, universe: Iterable[str] | None = None
    ) -> dict[str, Any] | None:
        """Cap weights {symbol: share} from the newest non-null ``market_quotes.market_cap`` per symbol fetched in
        the ``lookback_days`` before ``end``. The share is of the covered universe (``coverage`` symbols), not of the
        S&P 500; the event card says so. None when no caps are known (event earnings then read "not measured")."""
        hi = _aware(end)
        rows = self._rows(
            "SELECT DISTINCT ON (symbol) symbol, market_cap, fetched_at FROM market_quotes "
            "WHERE market_cap > 0 AND fetched_at <= %s AND fetched_at > %s "
            + ("AND symbol = ANY(%s) " if universe is not None else "")
            + "ORDER BY symbol, fetched_at DESC",
            [hi, hi - timedelta(days=int(lookback_days))] + ([[u.upper() for u in universe]] if universe else []),
        )
        caps = {r["symbol"]: float(r["market_cap"]) for r in rows if r.get("market_cap")}
        total = sum(caps.values())
        if not caps or total <= 0:
            return None
        newest = max((r["fetched_at"] for r in rows), default=None)
        return {
            "weights": {k: v / total for k, v in caps.items()},
            "as_of": _iso(newest),
            "coverage": len(caps),
            "source": "market_quotes.market_cap",
        }

    def etf_holdings(self, symbols: Iterable[str], *, end: datetime) -> list[dict[str, Any]]:
        """Newest ``etf_holdings_snapshot`` rows per ETF at or before ``end``. The store exists only once its §7A row
        is granted and the writer has run; until then this returns [] and sets ``etf_holdings_note``."""
        syms = [str(s).upper() for s in symbols]
        if not syms:
            return []
        try:
            cur = self._cur()
            cur.execute(
                "SELECT etf, holding, name, weight, as_of FROM etf_holdings_snapshot s WHERE etf = ANY(%s) AND as_of <= %s "
                "AND as_of = (SELECT max(as_of) FROM etf_holdings_snapshot t WHERE t.etf = s.etf AND t.as_of <= %s)",
                (syms, _aware(end), _aware(end)),
            )
            return [
                {"etf": r[0], "holding": r[1], "name": r[2], "weight": float(r[3]), "as_of": _iso(r[4])}
                for r in cur.fetchall()
            ]
        except Exception as exc:  # noqa: BLE001 — the store may not exist yet; look-through falls back to factsheets
            try:
                self._conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            self.etf_holdings_note = f"etf_holdings_snapshot unavailable: {type(exc).__name__}"
            return []

    def macro_calendar(self, *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        d0, d1 = _aware(start).astimezone(ET).date(), _aware(end).astimezone(ET).date()
        events: list[dict[str, Any]] = []
        try:
            try:
                from scripts.lib import macro_calendar as mc
            except ImportError:
                from lib import macro_calendar as mc  # type: ignore[no-redef]
            body = mc.load()
            for key, entry in body["dates"].items():
                d = date.fromisoformat(key)
                if d0 <= d <= d1:
                    for ev in entry["events"]:
                        ev = ev if isinstance(ev, dict) else {"event": str(ev)}
                        events.append(
                            {**ev, "date": key, "as_of": body.get("fetched_at"), "source": "macro_calendar.json"}
                        )
            return events
        except (FileNotFoundError, ValueError, KeyError) as exc:
            fallback_reason = f"{type(exc).__name__}: {exc}"
        self.macro_calendar_note = f"runtime calendar unavailable ({fallback_reason}); FOMC dates from overrides only"
        body = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        fomc = body.get("fomc") or {}
        for row in fomc.get("decision_dates") or []:
            d = date.fromisoformat(row["date"])
            if d0 <= d <= d1:
                events.append(
                    {
                        "date": row["date"],
                        "event": fomc.get("event", "fomc_decision"),
                        "name": fomc.get("name"),
                        "time_et": fomc.get("time_et"),
                        "sep": row.get("sep"),
                        "as_of": body.get("as_of"),
                        "source": "macro_calendar_overrides.json",
                        "note": f"runtime calendar unavailable ({fallback_reason})",
                    }
                )
        for row in body.get("add") or []:
            d = date.fromisoformat(row["date"])
            if d0 <= d <= d1:
                events.append({**row, "as_of": body.get("as_of"), "source": "macro_calendar_overrides.json"})
        return events
