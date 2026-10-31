"""As-of-correct ``DataReader`` over the committed scenario fixtures (design DSN-20261031-market-risk-engine §8).

The replay library and the backtest feed the engine through this reader instead of Postgres. Its one hard
guarantee is **no look-ahead**: every row carries the instant it became knowable (``as_of``), and no method
returns a row whose ``as_of`` is after the ``end`` it was asked for.

* Daily bars are knowable at that session's 16:00 ET close.
* FRED observations are knowable after their publication lag (``FRED_LAG_DAYS``; default one calendar day,
  VIXCLS two, matching the RCA's observed lag), stamped 20:00 UTC on the release day.
* Optional per-fixture JSON (``events.json``, ``option_snapshots.json``, ``sector_states.json``,
  ``regime_indicators.json``, ``extended_quotes.json``) rows must carry their own ``as_of``; absent files yield ``[]`` so the
  dependent category is UNKNOWN — never zero.
"""

from __future__ import annotations

import csv
import gzip
import json
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "market_risk_scenarios"
FRED_LAG_DAYS = {"VIXCLS": 2}
FRED_DEFAULT_LAG_DAYS = 1


def close_instant(d: date) -> datetime:
    """The UTC instant of the 16:00 ET close of session ``d``."""
    return datetime.combine(d, time(16, 0), tzinfo=ET).astimezone(timezone.utc)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("fixture reader needs tz-aware datetimes (naive would silently mean UTC or local)")
    return dt.astimezone(timezone.utc)


def _parse_ts(s: str) -> datetime:
    return _aware(datetime.fromisoformat(str(s).replace("Z", "+00:00")))


def _f(v: str) -> float | None:
    return None if v in ("", None) else float(v)


class FixtureReader:
    """``DataReader`` (scripts.lib.market_risk.contract) over a fixture directory."""

    def __init__(self, root: Path | str = FIXTURE_ROOT, *, overlay: Path | str | None = None):
        self.root = Path(root)
        self.overlay = Path(overlay) if overlay else None
        self._bars: dict[str, list[dict[str, Any]]] = {}
        self._fred: dict[str, list[dict[str, Any]]] = {}
        self._load()

    # ── loading ────────────────────────────────────────────────────────────────────────────
    def _open(self, name: str):
        p = self.root / name
        if not p.exists():
            return None
        return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")

    def _load(self) -> None:
        fh = self._open("bars.csv.gz")
        if fh:
            with fh:
                for r in csv.DictReader(fh):
                    d = date.fromisoformat(r["date"])
                    self._bars.setdefault(r["symbol"], []).append(
                        {
                            "symbol": r["symbol"],
                            "date": r["date"],
                            "open": _f(r["open"]),
                            "high": _f(r["high"]),
                            "low": _f(r["low"]),
                            "close": _f(r["close"]),
                            "volume": int(float(r["volume"] or 0)),
                            "as_of": close_instant(d).isoformat(),
                        }
                    )
        fh = self._open("fred.csv.gz")
        if fh:
            with fh:
                for r in csv.DictReader(fh):
                    d = date.fromisoformat(r["date"])
                    lag = FRED_LAG_DAYS.get(r["series"], FRED_DEFAULT_LAG_DAYS)
                    avail = datetime.combine(d + timedelta(days=lag), time(20, 0), tzinfo=timezone.utc)
                    self._fred.setdefault(r["series"], []).append(
                        {"series": r["series"], "date": r["date"], "value": _f(r["value"]), "as_of": avail.isoformat()}
                    )
        for rows in (*self._bars.values(), *self._fred.values()):
            rows.sort(key=lambda x: x["as_of"])

    def _json_rows(self, name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for base in (self.root, self.overlay):
            if base and (base / name).exists():
                data = json.loads((base / name).read_text(encoding="utf-8"))
                rows += data if isinstance(data, list) else data.get("rows", [])
        return rows

    @staticmethod
    def _upto(rows: list[dict[str, Any]], end: datetime) -> list[dict[str, Any]]:
        keys = [r["as_of"] for r in rows]
        return rows[: bisect_right(keys, _aware(end).isoformat())]

    # ── DataReader ─────────────────────────────────────────────────────────────────────────
    def sessions(self, *, start: date, end: date, symbol: str = "SPY") -> list[date]:
        return [
            date.fromisoformat(r["date"])
            for r in self._bars.get(symbol, [])
            if start <= date.fromisoformat(r["date"]) <= end
        ]

    def daily_bars(self, symbols: Iterable[str], *, sessions: int, end: datetime) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for s in symbols:
            out += self._upto(self._bars.get(s, []), end)[-int(sessions) :]
        return out

    def quotes(self, symbols: Iterable[str], *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Regular-session closes from the bars, plus any ``extended_quotes.json`` rows (session ``premarket`` /
        ``afterhours``, ``change_pct`` vs the prior regular close) knowable in [start, end]."""
        syms = list(symbols)
        lo = _aware(start).isoformat()
        out = [
            dict(r, price=r["close"], session="regular")
            for r in self.daily_bars(syms, sessions=10**6, end=end)
            if r["as_of"] >= lo
        ]
        out += [r for r in self._timed("extended_quotes.json", end, start=start) if r.get("symbol") in set(syms)]
        return sorted(out, key=lambda r: _parse_ts(r["as_of"]))

    def fred(self, series: Iterable[str], *, observations: int, end: datetime) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for s in series:
            out += self._upto(self._fred.get(s, []), end)[-int(observations) :]
        return out

    def _timed(self, name: str, end: datetime, *, start: datetime | None = None, key: str = "as_of") -> list[dict]:
        hi = _aware(end)
        lo = _aware(start) if start else None
        out = []
        for r in self._json_rows(name):
            ts = _parse_ts(r[key])
            if ts <= hi and (lo is None or ts >= lo):
                out.append(r)
        return sorted(out, key=lambda r: r[key])

    def regime_indicators(self, *, end: datetime) -> list[dict[str, Any]]:
        return self._timed("regime_indicators.json", end)

    def option_snapshots(self, symbols: Iterable[str], *, sessions: int, end: datetime) -> list[dict[str, Any]]:
        want = set(symbols)
        rows = [r for r in self._timed("option_snapshots.json", end) if r.get("symbol") in want]
        return rows[-int(sessions) * max(1, len(want)) :]

    def sector_states(self, *, end: datetime) -> list[dict[str, Any]]:
        return self._timed("sector_states.json", end)

    def _events(self, kind: str, start: datetime, end: datetime, now: datetime | None) -> list[dict[str, Any]]:
        """Scheduled events are knowable when announced (``as_of``); returned when the event time is in
        [start, end] and, if ``now`` is given, the announcement precedes ``now``."""
        lo, hi = _aware(start), _aware(end)
        out = []
        for r in self._json_rows("events.json"):
            if r.get("kind") != kind:
                continue
            at = _parse_ts(r["at"])
            if lo <= at <= hi and (now is None or _parse_ts(r["as_of"]) <= _aware(now)):
                out.append(r)
        return sorted(out, key=lambda r: r["at"])

    def index_weights(self, *, end: datetime, universe: Iterable[str] | None = None) -> dict[str, Any] | None:
        """``index_weights.json`` ({"as_of", "weights": {symbol: share}}) when the scenario ships one, else None.
        The public fixtures carry no per-company weights, so replayed earnings concentration reads "not measured"."""
        rows = [r for r in self._timed("index_weights.json", end)] if self._has("index_weights.json") else []
        return rows[-1] if rows else None

    def _has(self, name: str) -> bool:
        return any(b and (b / name).exists() for b in (self.root, self.overlay))

    def earnings_calendar(self, *, start: datetime, end: datetime, now: datetime | None = None) -> list[dict]:
        return self._events("earnings", start, end, now)

    def macro_calendar(self, *, start: datetime, end: datetime, now: datetime | None = None) -> list[dict]:
        return self._events("macro", start, end, now)
