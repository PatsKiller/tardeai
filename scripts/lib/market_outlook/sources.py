"""The Market Outlook read layer — as-of correct, read-only, banned feeds refused.

The bundle is a plain dict (``Bundle.to_dict``) so a test fixture, a replay and the live read share one shape, and the
record's ``inputs_snapshot_hash`` is a hash of exactly what the engine scored (§4.6).

Rules (FABLE-OUTLOOK-METHODOLOGY-LQ-946 §1, §2.1):
* nothing observed after ``now`` is read (``created_at``/``fetched_at`` <= now, business date <= the ET date of now);
* every row carries ``as_of`` and its feed/source;
* a row whose feed is in ``sources.banned_feeds`` is refused with a reason and never scored (yfinance/yahoo);
* read-only: the connection is opened read-only and the session is set ``default_transaction_read_only``.

Production connects through ``scripts.session13_db.get_conn`` (the lane's bound environment). The local, credential-free
path is ``--db peer``: the same Postgres over the unix socket with the read-only peer role documented in WORKERS.md
("Every worker has read-only Postgres", 2026-11-07).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

#: The eleven category indicators' tables, in the order the audit trail lists them (§1).
#: Futures roots as ``market_quotes_extended`` spells them (``/ES``, ``/ESZ26``); a contract matches its root by prefix.
FUTURES_SYMBOLS = ("/ES", "/NQ", "/RTY", "/YM")
CASH_INDEX_SYMBOLS = ("$SPX", "$NDX", "$DJI", "$RUT", "$COMPX")


# ── bundle -----------------------------------------------------------------------------------------------------
class Bundle:
    """Everything one evaluation may look at, keyed by the policy's own names."""

    SECTIONS = (
        "bars",
        "fred",
        "snapshots",
        "movers",
        "sector_rs",
        "sector_states",
        "options",
        "extended",
        "regime",
        "macro_events",
        "overrides",
        "refused",
    )

    def __init__(self, as_of: str, **sections: Any):
        self.as_of = as_of
        for name in self.SECTIONS:
            setattr(self, name, sections.get(name) if sections.get(name) is not None else _empty(name))
        self.mre = sections.get("mre")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"as_of": self.as_of}
        for name in self.SECTIONS:
            out[name] = getattr(self, name)
        out["mre"] = self.mre
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Bundle":
        missing = [k for k in cls.SECTIONS if k not in data and k not in ("mre",)]
        if missing:
            raise ValueError(f"bundle fixture missing sections {missing}")
        return cls(data.get("as_of") or "", **{k: data.get(k) for k in cls.SECTIONS + ("mre",)})

    def symbols(self) -> set[str]:
        """Every symbol any section carries — the read set a stub source can record."""
        out: set[str] = set(self.bars) | set(self.fred) | set(self.options)
        for row in self.extended:
            out.add(str(row.get("symbol")))
        return {s for s in out if s}


def _empty(name: str) -> Any:
    return {} if name in ("bars", "fred", "options", "regime", "overrides", "sector_rs") else (
        [] if name in ("sector_states", "extended", "macro_events", "refused") else None
    )


# ── production reader ------------------------------------------------------------------------------------------
def _peer_conn():
    """Read-only Postgres over the unix socket as the current OS role (WORKERS.md read-only peer path)."""
    import getpass

    import psycopg2

    conn = psycopg2.connect(
        host=os.environ.get("TRADEAI_PG_HOST", "/var/run/postgresql"),
        dbname=os.environ.get("TRADEAI_PG_DB", "trade_ai"),
        user=os.environ.get("TRADEAI_PG_USER") or getpass.getuser(),
        options="-c default_transaction_read_only=on",
        connect_timeout=10,
    )
    conn.set_session(readonly=True)
    return conn


def _app_conn():
    """The lane's own bound connection (n8n executor / host env). Read-only session."""
    try:
        from scripts.session13_db import get_conn
    except ImportError:  # scripts/ on sys.path
        from session13_db import get_conn  # type: ignore[no-redef]

    conn = get_conn()
    if hasattr(conn, "set_session"):
        conn.set_session(readonly=True)
    elif hasattr(conn, "read_only"):
        conn.read_only = True
    else:  # an unroutable connection is refused rather than used read-write
        conn.close()
        raise RuntimeError("market outlook reader: connection cannot be made read-only; refusing")
    return conn


def _state_root(explicit: Path | str | None = None) -> Path:
    from . import state_root as srmod

    return srmod.resolve(explicit)


class PgOutlookSource:
    """Reads the existing tables in §1 (plus the MRE runtime JSON). Never writes, never reads a banned feed."""

    def __init__(
        self,
        policy: dict[str, Any],
        *,
        conn_factory: Callable[[], Any] | None = None,
        mre_path: Path | str | None = None,
        state_root: Path | str | None = None,
    ):
        self.policy = policy
        self.sources_cfg = policy["sources"]
        self._factory = conn_factory or _app_conn
        self._conn = None
        root = _state_root(state_root)
        self.mre_path = Path(mre_path) if mre_path else root / str(policy["regimes"]["mre_latest"])
        self.state_root = root

    # plumbing ------------------------------------------------------------------------------------------------
    def _cur(self):
        if self._conn is None:
            self._conn = self._factory()
        return self._conn.cursor()

    def _rows(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = self._cur()
        try:
            cur.execute(sql, list(params))
            names = [c[0] for c in cur.description]
            return [{k: _plain(v) for k, v in zip(names, r)} for r in cur.fetchall()]
        finally:
            cur.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # sections ------------------------------------------------------------------------------------------------
    def bars(self, symbols: list[str], now: datetime) -> dict[str, list[dict[str, Any]]]:
        allowed = list(self.sources_cfg["daily_bar_sources"])
        rows = self._rows(
            "SELECT symbol, bar_time, open, high, low, close, source, created_at FROM market_ohlcv_bars "
            "WHERE timeframe = 'daily' AND symbol = ANY(%s) AND source = ANY(%s) "
            "AND created_at <= %s AND bar_time <= %s ORDER BY symbol, bar_time",
            [symbols, allowed, now, now],
        )
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            if str(r["source"]) in {str(b) for b in self.sources_cfg["banned_feeds"]}:
                continue  # belt and braces: the SQL already excludes them
            out.setdefault(str(r["symbol"]), []).append(
                {
                    "date": str(r["bar_time"])[:10],
                    "close": float(r["close"]),
                    "high": _f(r.get("high")),
                    "low": _f(r.get("low")),
                    "source": str(r["source"]),
                    "as_of": str(r["created_at"]),
                }
            )
        return out

    def fred(self, series: list[str], now: datetime) -> dict[str, list[dict[str, Any]]]:
        rows = self._rows(
            "SELECT series_id, observation_date, value, fetched_at FROM fred_economic_series "
            "WHERE series_id = ANY(%s) AND fetched_at <= %s AND observation_date <= %s "
            "ORDER BY series_id, observation_date",
            [series, now, now.astimezone(ET).date()],
        )
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            if r["value"] is None:
                continue
            out.setdefault(str(r["series_id"]), []).append(
                {
                    "date": str(r["observation_date"]),
                    "value": float(r["value"]),
                    "as_of": str(r["fetched_at"]),
                }
            )
        return out

    def snapshots(self, now: datetime) -> dict[str, Any] | None:
        table = self.sources_cfg["snapshot_table"]
        rows = self._rows(
            f"SELECT snapshot_date, count(*) AS n, "
            f"count(*) FILTER (WHERE sma20_pct > 0) AS above20, "
            f"count(*) FILTER (WHERE sma50_pct > 0) AS above50, "
            f"count(*) FILTER (WHERE sma200_pct > 0) AS above200 "
            f"FROM {table} WHERE snapshot_date = ("
            f"  SELECT max(snapshot_date) FROM {table} WHERE snapshot_date <= %s AND created_at <= %s) "
            f"GROUP BY 1",
            [now.astimezone(ET).date(), now],
        )
        if not rows or not rows[0]["n"]:
            return None
        r = rows[0]
        n = int(r["n"])
        return {
            "date": str(r["snapshot_date"]),
            "n": n,
            "pct_above_sma20": 100.0 * int(r["above20"]) / n,
            "pct_above_sma50": 100.0 * int(r["above50"]) / n,
            "pct_above_sma200": 100.0 * int(r["above200"]) / n,
            "as_of": str(r["snapshot_date"]),
        }

    def movers(self, now: datetime) -> dict[str, Any] | None:
        table = self.sources_cfg["movers_table"]
        window = int(self.sources_cfg["movers_batch_window_minutes"])
        rows = self._rows(
            f"SELECT signal, symbol, change_pct, captured_at FROM {table} "
            f"WHERE captured_at <= %s AND captured_at >= ("
            f"  SELECT max(captured_at) FROM {table} WHERE captured_at <= %s) - make_interval(mins => %s)",
            [now, now, window],
        )
        if not rows:
            return None
        by_signal: dict[str, dict[str, float]] = {}
        as_of = max(str(r["captured_at"]) for r in rows)
        for r in rows:
            sig = str(r["signal"])
            sym = str(r["symbol"])
            by_signal.setdefault(sig, {}).setdefault(sym, float(r["change_pct"] or 0.0))
        counts = {sig: len(syms) for sig, syms in by_signal.items()}
        gvals = list(by_signal.get("top_gainers", {}).values())
        lvals = list(by_signal.get("top_losers", {}).values())
        return {
            "as_of": as_of,
            "counts": counts,
            "new_high": counts.get("new_high", 0),
            "new_low": counts.get("new_low", 0),
            "gainers_mean_change": sum(gvals) / len(gvals) if gvals else None,
            "losers_mean_change": sum(lvals) / len(lvals) if lvals else None,
        }

    def sector_rs(self, now: datetime, sessions: int) -> dict[str, Any]:
        table = self.sources_cfg["sector_rs_table"]
        rows = self._rows(
            f"SELECT rs_date, symbol, rs FROM {table} WHERE rs_date <= %s "
            f"AND rs_date >= %s::date - make_interval(days => %s) ORDER BY rs_date",
            [now.astimezone(ET).date(), now.astimezone(ET).date(), int(sessions) * 3],
        )
        dates: list[str] = []
        series: dict[str, dict[str, float]] = {}
        for r in rows:
            d = str(r["rs_date"])
            if d not in series:
                dates.append(d)
                series[d] = {}
            series[d][str(r["symbol"])] = float(r["rs"])
        return {"dates": dates, "by_date": series}

    def sector_states(self, now: datetime) -> list[dict[str, Any]]:
        table = self.sources_cfg["sector_state_table"]
        rows = self._rows(
            f"SELECT as_of, etf, sector, state, breadth_pct FROM {table} WHERE as_of = ("
            f"  SELECT max(as_of) FROM {table} WHERE as_of <= %s AND created_at <= %s)",
            [now.astimezone(ET).date(), now],
        )
        return [
            {
                "as_of": str(r["as_of"]),
                "etf": str(r["etf"]),
                "sector": r.get("sector"),
                "state": str(r["state"]) if r["state"] is not None else None,
                "breadth_pct": float(r["breadth_pct"]) if r["breadth_pct"] is not None else None,
            }
            for r in rows
        ]

    def options(self, symbols: list[str], now: datetime) -> dict[str, list[dict[str, Any]]]:
        table = self.sources_cfg["options_table"]
        rows = self._rows(
            f"SELECT symbol, as_of, pc_vol_ratio, pc_oi_ratio, created_at FROM {table} "
            f"WHERE symbol = ANY(%s) AND as_of <= %s AND created_at <= %s ORDER BY symbol, as_of",
            [symbols, now.astimezone(ET).date(), now],
        )
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            out.setdefault(str(r["symbol"]), []).append(
                {
                    "as_of": str(r["as_of"]),
                    "pc_vol_ratio": _f(r["pc_vol_ratio"]),
                    "pc_oi_ratio": _f(r["pc_oi_ratio"]),
                }
            )
        return out

    def extended(self, symbols: list[str], now: datetime, days: int) -> list[dict[str, Any]]:
        table = self.sources_cfg["extended_table"]
        # a futures root (/ES) must also match its dated contract (/ESZ26), which is what the lane writes after a roll
        patterns = [f"{s}%" for s in symbols if str(s).startswith("/")]
        rows = self._rows(
            f"SELECT symbol, session, bar_start, bar_end, price, reference_close, change_pct, feed FROM {table} "
            f"WHERE (symbol = ANY(%s) OR symbol LIKE ANY(%s)) AND bar_start <= %s "
            f"AND bar_start >= %s - make_interval(days => %s) ORDER BY symbol, bar_start",
            [symbols, patterns or [""], now, now, int(days)],
        )
        return [
            {
                "symbol": str(r["symbol"]),
                "session": str(r["session"]),
                "bar_start": str(r["bar_start"]),
                "price": _f(r["price"]),
                "reference_close": _f(r["reference_close"]),
                "change_pct": _f(r["change_pct"]),
                "feed": str(r["feed"]),
            }
            for r in rows
        ]

    def regime(self, now: datetime) -> dict[str, dict[str, Any]]:
        table = self.sources_cfg["regime_table"]
        rows = self._rows(
            f"SELECT indicator_key, value, source_key, created_at FROM {table} WHERE created_at = ("
            f"  SELECT max(created_at) FROM {table} WHERE created_at <= %s)",
            [now],
        )
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r.get("value") is None:
                continue
            out[str(r["indicator_key"])] = {
                "value": _f(r["value"]),
                "feed": str(r["source_key"] or ""),
                "as_of": str(r["created_at"]),
            }
        return out

    def macro_events(self, now: datetime, horizon_days: int) -> list[dict[str, Any]]:
        from . import calendar

        return calendar.read_macro_events(now, horizon_days=horizon_days)

    def mre(self, now: datetime) -> dict[str, Any] | None:
        try:
            body = json.loads(Path(self.mre_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("market outlook: MRE latest unreadable at %s (%s)", self.mre_path, exc)
            return None
        return body if isinstance(body, dict) else None

    # the whole bundle --------------------------------------------------------------------------------------
    def bundle(self, *, now: datetime, extra_symbols: list[str] | None = None) -> Bundle:
        p = self.policy
        cats = {c["key"]: c for c in p["categories"]}
        symbols: set[str] = set(extra_symbols or [])
        for cat in p["categories"]:
            for ind in cat["indicators"]:
                for field in ("etf_symbol", "numerator", "denominator", "symbol"):
                    if ind.get(field):
                        symbols.add(str(ind[field]))
                if ind.get("cash_symbol"):
                    symbols.add(str(ind["cash_symbol"]))
        fred_series: set[str] = set()
        for cat in p["categories"]:
            for ind in cat["indicators"]:
                if ind.get("fred_series"):
                    fred_series.add(str(ind["fred_series"]))
        opt_symbols: set[str] = set()
        for ind in cats["positioning"]["indicators"]:
            opt_symbols.update(str(s) for s in ind.get("symbols") or [])
        extended_symbols = list(FUTURES_SYMBOLS) + list(CASH_INDEX_SYMBOLS)

        refused: list[dict[str, Any]] = []
        bars = self.bars(sorted(symbols), now)
        regime = self.regime(now)
        # §1.14: the VIX complex is still Yahoo-written. Read it so the refusal is recorded, never score it.
        for key, row in regime.items():
            if str(row.get("feed", "")).lower() in {str(b).lower() for b in self.sources_cfg["banned_feeds"]}:
                refused.append(
                    {
                        "key": key,
                        "feed": row.get("feed"),
                        "as_of": row.get("as_of"),
                        "reason": f"banned feed {row.get('feed')!r} (operator price rule: never yfinance/yahoo)",
                    }
                )
        return Bundle(
            as_of=now.astimezone(timezone.utc).isoformat(),
            bars=bars,
            fred=self.fred(sorted(fred_series), now),
            snapshots=self.snapshots(now),
            movers=self.movers(now),
            sector_rs=self.sector_rs(now, sessions=int(p["normalization"]["z"]["window_sessions"])),
            sector_states=self.sector_states(now),
            options=self.options(sorted(opt_symbols), now),
            extended=self.extended(extended_symbols, now, days=8),
            regime=regime,
            macro_events=self.macro_events(now, int(p["events"]["horizon_days"])),
            overrides=_overrides(),
            mre=self.mre(now),
            refused=refused,
        )


def _overrides() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "config" / "macro_calendar_overrides.json"
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        return {"fomc": body.get("fomc") or {}, "as_of": body.get("as_of"), "schema": body.get("schema")}
    except (OSError, ValueError):
        return {"fomc": {}, "as_of": None, "schema": None}


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _plain(v: Any) -> Any:
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if hasattr(v, "isoformat") and not isinstance(v, str):
        return v.isoformat()
    return v


def load_bundle(
    policy: dict[str, Any],
    *,
    now: datetime,
    fixture: Path | str | None = None,
    db: str = "app",
    state_root: Path | str | None = None,
) -> Bundle:
    """The one entry point: a fixture bundle for a test/replay, else the production read."""
    if fixture:
        return Bundle.from_dict(json.loads(Path(fixture).read_text(encoding="utf-8")))
    factory = _peer_conn if db == "peer" else _app_conn
    src = PgOutlookSource(policy, conn_factory=factory, state_root=state_root)
    try:
        return src.bundle(now=now)
    finally:
        src.close()


__all__ = ["Bundle", "PgOutlookSource", "load_bundle", "FUTURES_SYMBOLS", "CASH_INDEX_SYMBOLS"]
