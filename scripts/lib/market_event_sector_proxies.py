"""market_event_sector_proxies — sector moves from reference daily bars (LQ-20261107-382, WP1 second source).

Operator ask 17:55 ET 2026-11-07: "market indicators beyond QQQ". ``config/market_event_policy.json``
``detector.index_symbols`` was SPY and QQQ, and the only sector signal the detector could see was the MRE's
``sectors.groups`` (Finviz-derived, one proxy ETF per group, and a group with no daily bar is UNKNOWN). This module
is the *second* sector source: it reads the reference ETFs' daily bars from ``market_ohlcv_bars`` — the series the
``market-reference-bars`` lane refreshes from Alpaca — and computes each group's own return and its return relative
to the benchmark over the benchmark's own session calendar.

Pure functions (tested on synthetic rows): ``load_proxy_groups``, ``series_from_rows``, ``build_moves``,
``sector_hits``. DB reader: ``read_closes``, ``read_moves`` (read-only SELECT; the caller owns the connection).

Where the proxy map comes from, in order of precedence:

1. ``policy["detector"]["sector_proxies"]`` — ``{"benchmark": "SPY", "groups": {key: {"label", "proxy", "kind"}}}``;
2. ``config/market_reference_symbols.json`` ``"proxy_groups"`` — the same shape, shipped with the symbols it names.

Keys are chosen to match ``config/market_risk_policy.yaml`` ``sectors.groups`` keys wherever a group exists there,
so an ``affected_groups`` name resolves in both sources and a hit from either one joins.

Truth rules this module keeps (the audit habit that keeps a source honest):

* **Missing is UNKNOWN, never a zero.** A group with no close on either endpoint of a window has that window
  ``None`` and a named ``reason``; it is never reported as a flat 0% move.
* **Staleness is visible.** A proxy whose last bar lags the benchmark's last session by more than
  ``max_stale_sessions`` is ``stale: true`` with ``sessions_behind`` and contributes no hit — an October move must
  not fire a November trigger.
* **The benchmark owns the calendar.** Windows are measured on the benchmark's session dates and require the proxy
  to have a close at both endpoints, so a group's 5-session move and SPY's 5-session move cover the same days.
* **Advisory only** (``MBI_BEHAVIOR = 0``): this module produces labels and returns. It never sizes, orders, stops,
  weights or reaches a broker.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:  # runnable as `python scripts/lib/market_event_sector_proxies.py`
    sys.path.insert(0, str(ROOT / "scripts"))
SYMBOLS_PATH = ROOT / "config" / "market_reference_symbols.json"
SCHEMA = "MarketEventSectorMoves@v1"
SOURCE = "market_ohlcv_bars:daily"
DEFAULT_BENCHMARK = "SPY"
HORIZONS = (1, 5, 20)
#: Alpaca is the granted `bars` source (config/data_source_authority.json). A yfinance row is still readable — the
#: reference series was yfinance until 2026-11-07 — but alpaca wins a duplicate (symbol, session) and the winning
#: source is reported per group, so a reader can tell which vendor a move came from.
SOURCE_PREFERENCE = ("alpaca",)
LOOKBACK_DAYS = 120  # 20 sessions plus weekends/holidays and the staleness window
STATE_UNDER = "UNDERPERFORMING"
STATE_OVER = "OUTPERFORMING"
STATE_IN = "INLINE"
STATE_UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------------------------- proxy map
def load_proxy_groups(policy: Mapping[str, Any] | None = None,
                      path: Path | str | None = None) -> dict[str, Any]:
    """``{"benchmark", "groups": {key: {"label", "proxy", "kind"}}, "origin"}``.

    ``policy["detector"]["sector_proxies"]`` wins when it carries groups; else the shipped
    ``proxy_groups`` block in ``config/market_reference_symbols.json``. An empty or unreadable map returns
    ``groups: {}`` plus ``origin`` naming why — the caller reports UNKNOWN, never a silent empty success.
    """
    det = (policy or {}).get("detector") or {}
    block = det.get("sector_proxies")
    origin = "policy:detector.sector_proxies"
    if not isinstance(block, Mapping) or not (block.get("groups") or {}):
        origin = "config:market_reference_symbols.json:proxy_groups"
        try:
            doc = json.loads(Path(path or SYMBOLS_PATH).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"benchmark": DEFAULT_BENCHMARK, "groups": {}, "origin": f"{origin} unreadable: {type(exc).__name__}"}
        if doc.get("schema") != "MarketReferenceSymbols@v1":
            return {"benchmark": DEFAULT_BENCHMARK, "groups": {},
                    "origin": f"{origin} wrong schema {doc.get('schema')!r}"}
        block = doc.get("proxy_groups") or {}
    groups: dict[str, dict[str, Any]] = {}
    for key, g in (block.get("groups") or {}).items():
        proxy = str((g or {}).get("proxy") or "").strip().upper()
        if not key or not proxy:
            continue  # a half-written group is not a group; it would otherwise read as a symbol named ""
        groups[str(key)] = {"label": (g or {}).get("label") or str(key), "proxy": proxy,
                            "kind": (g or {}).get("kind") or "sector"}
    return {"benchmark": str(block.get("benchmark") or DEFAULT_BENCHMARK).upper(), "groups": groups, "origin": origin}


# ---------------------------------------------------------------------------------------------- series
def series_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[tuple[str, float, str]]]:
    """Group bar rows into ``{symbol: [(session_iso, close, source)]}`` sorted by session.

    One close per (symbol, session): an alpaca row beats any other vendor, then the later row beats the earlier one,
    so a re-run of the loader that rewrote the same bar leaves the same series. Non-positive or missing closes are
    dropped (a zero close would make every ratio infinite or NaN).
    """
    rank_of = {s: i for i, s in enumerate(SOURCE_PREFERENCE)}
    best: dict[tuple[str, str], tuple[int, float, str]] = {}
    for r in rows:
        try:
            sym = str(r["symbol"]).strip().upper()
            day = str(r.get("session") or r.get("bar_time"))[:10]
            close = float(r["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if not sym or not day or close <= 0:
            continue
        src = str(r.get("source") or "")
        prio = rank_of.get(src, len(rank_of) + 1)
        prev = best.get((sym, day))
        if prev is None or prio <= prev[0]:
            best[(sym, day)] = (prio, close, src)
    out: dict[str, list[tuple[str, float, str]]] = {}
    for (sym, day), (_prio, close, src) in sorted(best.items()):
        out.setdefault(sym, []).append((day, close, src))
    return out


def _closes(series: list[tuple[str, float, str]]) -> dict[str, float]:
    return {d: c for d, c, _ in series}


def _ret(closes: Mapping[str, float], cal: list[str], n: int) -> float | None:
    """Return over ``n`` benchmark sessions ending at the calendar's last session; None unless both endpoints exist."""
    if len(cal) <= n:
        return None
    a, b = closes.get(cal[-1 - n]), closes.get(cal[-1])
    if a is None or b is None or a <= 0:
        return None
    return round((b / a - 1.0) * 100.0, 3)


def _state(ret: float | None, rel: float | None, rel_move_pct: float) -> str:
    if ret is None or rel is None:
        return STATE_UNKNOWN
    if rel <= -abs(rel_move_pct):
        return STATE_UNDER
    if rel >= abs(rel_move_pct):
        return STATE_OVER
    return STATE_IN


def build_moves(rows: Iterable[Mapping[str, Any]], groups: Mapping[str, Mapping[str, Any]], *,
                as_of: str, benchmark: str = DEFAULT_BENCHMARK, horizons: Iterable[int] = HORIZONS,
                max_stale_sessions: int = 2, rel_move_pct: float = 5.0,
                rel_field: str = "rs5") -> dict[str, Any]:
    """The ``MarketEventSectorMoves@v1`` document. Pure: rows in, document out, no clock and no DB."""
    hs = tuple(int(h) for h in horizons)
    series = series_from_rows(rows)
    bench_series = series.get(benchmark) or []
    cal = [d for d, _, _ in bench_series]
    bench_closes = _closes(bench_series)
    bench_ret = {f"ret{h}": _ret(bench_closes, cal, h) for h in hs}
    out_groups: dict[str, Any] = {}
    for key in sorted(groups):
        g = groups[key]
        proxy = str(g["proxy"]).upper()
        s = series.get(proxy) or []
        last = s[-1][0] if s else None
        sessions_behind = len([d for d in cal if last is None or d > last]) if cal else None
        stale = bool(cal) and (last is None or (sessions_behind or 0) > max_stale_sessions)
        cl = _closes(s)
        rets = {f"ret{h}": _ret(cl, cal, h) for h in hs}
        rels = {f"rs{h}": (None if rets[f"ret{h}"] is None or bench_ret[f"ret{h}"] is None
                           else round(rets[f"ret{h}"] - bench_ret[f"ret{h}"], 3)) for h in hs}
        reason = None
        if not cal:
            reason = f"benchmark {benchmark} has no daily bars"
        elif not s:
            reason = f"no daily bars for {proxy}"
        elif stale:
            reason = f"{proxy} last bar {last} is {sessions_behind} sessions behind {cal[-1]}"
        out_groups[key] = {
            "label": g.get("label") or key,
            "proxy": proxy,
            "kind": g.get("kind") or "sector",
            "last": last,
            "sessions_behind": sessions_behind,
            "stale": stale,
            "close": round(s[-1][1], 4) if s else None,
            "source": s[-1][2] if s else None,
            **rets,
            **rels,
            "state": STATE_UNKNOWN if stale or not cal else _state(
                rets.get(f"ret{rel_field[2:]}"), rels.get(rel_field), rel_move_pct),
            "reason": reason,
        }
    return {
        "schema": SCHEMA,
        "as_of": as_of,
        "source": SOURCE,
        "benchmark": benchmark,
        "calendar_last": cal[-1] if cal else None,
        "calendar_sessions": len(cal),
        "horizons": list(hs),
        "rel_move_pct": rel_move_pct,
        "benchmark_return": bench_ret,
        "groups": out_groups,
        # a proxy that never had a bar is UNKNOWN ("no daily bars"), not "stale": it lags nothing, it is absent
        "stale": sorted(k for k, v in out_groups.items() if v["stale"] and v["last"]),
        "unknown": sorted(k for k, v in out_groups.items() if v["state"] == STATE_UNKNOWN),
    }


def sector_hits(doc: Mapping[str, Any], *, rel_field: str = "rs5", rel_move_pct: float = 5.0,
                kinds: Iterable[str] = ("sector", "theme")) -> list[dict[str, Any]]:
    """Groups whose ``rel_field`` is at or below ``-rel_move_pct``, in the detector's ``sector_hits`` shape.

    A stale or UNKNOWN group never produces a hit: the whole point of this second source is that a move is current
    as of the session the reader names.
    """
    kind_set = set(kinds)
    out = []
    for key, g in sorted((doc.get("groups") or {}).items()):
        if g.get("kind") not in kind_set or g.get("stale") or g.get("state") == STATE_UNKNOWN:
            continue
        rel = g.get(rel_field)
        if rel is None or float(rel) > -abs(rel_move_pct):
            continue
        out.append({"group": key, "proxy": g.get("proxy"), "kind": g.get("kind"), rel_field: rel,
                    "last": g.get("last"), "source": "reference_bars"})
    return out


def merge_sector_hits(mre_hits: Iterable[Mapping[str, Any]],
                      bar_hits: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The detector's merged ``sectors`` list: MRE hits first, then reference-bar hits for groups the MRE did not
    already name. A group in both keeps the MRE hit — MRE carries the group's state and z-score evidence, and the
    same group named twice would open the same ``sector_rotation`` episode twice."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in list(mre_hits) + list(bar_hits):
        key = str(h.get("group")) if h.get("group") is not None else ""
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(dict(h))
    return out


# ---------------------------------------------------------------------------------------------- DB reader
def read_closes(conn, symbols: Iterable[str], *, end: date | None = None,
                lookback_days: int = LOOKBACK_DAYS) -> list[dict[str, Any]]:
    """Daily closes for ``symbols`` up to ``end`` (inclusive), read-only. ``end`` bounds the read so a replay sees
    only what existed then."""
    syms = sorted({str(s).strip().upper() for s in symbols if str(s).strip()})
    if not syms:
        return []
    end = end or datetime.now(timezone.utc).date()
    cur = conn.cursor()
    cur.execute(
        "SELECT symbol, bar_time::date AS session, close, source FROM market_ohlcv_bars "
        "WHERE timeframe = 'daily' AND symbol = ANY(%s) AND close IS NOT NULL "
        "AND bar_time >= %s AND bar_time < %s "
        "ORDER BY symbol, bar_time",
        (syms, end - timedelta(days=int(lookback_days)), end + timedelta(days=1)),
    )
    return [{"symbol": r[0], "session": str(r[1]), "close": r[2], "source": r[3]} for r in cur.fetchall()]


def read_moves(conn, policy: Mapping[str, Any] | None = None, *, now: datetime | None = None,
               end: date | None = None, path: Path | str | None = None) -> dict[str, Any]:
    """Load the map, read the bars, build the document. The benchmark's last bar sets ``calendar_last``."""
    now = now or datetime.now(timezone.utc)
    proxies = load_proxy_groups(policy, path)
    symbols = [g["proxy"] for g in proxies["groups"].values()] + [proxies["benchmark"]]
    rows = read_closes(conn, symbols, end=end)
    det_open = ((policy or {}).get("detector") or {}).get("open") or {}
    rel_field = str(det_open.get("sector_rel_field") or "rs5")
    rel_move_pct = float(det_open.get("sector_rel_move_pct") or 5.0)
    doc = build_moves(rows, proxies["groups"], as_of=now.isoformat(), benchmark=proxies["benchmark"],
                      rel_move_pct=rel_move_pct, rel_field=rel_field,
                      max_stale_sessions=int(((policy or {}).get("data") or {}).get("sector_proxy_max_stale_sessions") or 2))
    doc["origin"] = proxies["origin"]
    doc["hits"] = sector_hits(doc, rel_field=rel_field, rel_move_pct=rel_move_pct,
                              kinds=det_open.get("sector_group_kinds") or ("sector", "theme"))
    return doc


# ---------------------------------------------------------------------------------------------- CLI (evidence only)
def _connect_read_only():
    from lib import ops_lanes
    env_file = Path(os.environ.get("TRADEAI_ENV_FILE") or ROOT / ".env")
    conn = ops_lanes.pg_connect(ops_lanes.db_params(env_file=env_file), read_only=True)
    from lib import lane_last_receipt
    lane_last_receipt.enforce_readonly(conn)
    return conn


def main(argv: list[str] | None = None) -> int:
    """Print the document from the live DB, read-only. Evidence and debugging only: this module has no scheduler
    and writes nothing."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--policy", default=str(ROOT / "config" / "market_event_policy.json"))
    ap.add_argument("--symbols", default=str(SYMBOLS_PATH))
    ap.add_argument("--now", default=None, help="ISO instant for as_of (default: now)")
    ap.add_argument("--json", action="store_true", help="the whole document (default: one line)")
    args = ap.parse_args(argv)
    policy = {}
    try:
        policy = json.loads(Path(args.policy).read_text())
    except (OSError, ValueError):
        pass  # the config map is the fallback; the document names its origin
    conn = _connect_read_only()
    try:
        now = datetime.fromisoformat(args.now) if args.now else None
        doc = read_moves(conn, policy, now=now, path=args.symbols)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if args.json:
        print(json.dumps(doc, indent=1, sort_keys=True))
    else:
        print(json.dumps({"schema": doc["schema"], "origin": doc["origin"], "calendar_last": doc["calendar_last"],
                          "groups": len(doc["groups"]), "measured": len(doc["groups"]) - len(doc["unknown"]),
                          "unknown": doc["unknown"], "stale": doc["stale"], "hits": doc["hits"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
