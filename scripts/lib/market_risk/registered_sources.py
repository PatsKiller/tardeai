"""Engine inputs derived from sources the platform ALREADY fetches under existing §7A rows — no new provider,
no new fetch, no broker call (operator 2026-10-31: "We also have Charles Schwab and moomoo apis to use and finviz").

* ``implied_moves`` — expected move per symbol from the Schwab option-chain snapshots the host lane already stores
  (``option_chain_snapshots.atm_iv`` × underlying × sqrt(sessions/252)). Feeds the protection playbook and the deep
  brief ("implied moves for held names / sector ETFs"). Read through ``PgReader.option_snapshots`` (as-of correct).
* ``chain_daily_closes`` — a PROVISIONAL daily close for symbols that have no ``market_ohlcv_bars`` (XLC, XLRE …):
  the underlying price of the EARLIEST chain snapshot inside the close window (close_time(d) to close_time(d) + 15
  min) on an NYSE trading day. Later after-hours snapshots (the 17:35 run) and weekend runs never make a close, so
  with today's 10:00/17:35 schedule this returns nothing — that is honest, not a bug. Labelled
  ``provisional_chain_snapshot``.
* ``implied_moves`` carries ``dq_flags`` when the newest ATM IV is out of line with the symbol's own trailing median
  (ratio outside [1/k, k], k from the caller; default 1.8) — e.g. XLC 0.72 vs a ~0.25 median.
* ``finviz_positioning`` — institutional / insider transaction %, short float, trend vs the 20/50/200-day averages and
  performance, from the Finviz enrichment cache file (registered domain ``finviz_enrichment``; records carry no
  per-row source field, so attribution is by file). A record is knowable only when BOTH its ``cached_at`` and its
  ``hot_cached_at`` (hot fields such as ``rvol`` refresh under it) are at or before ``end``.

Unknown is not zero: a symbol with no usable row is absent from the result, never filled with 0.
Advisory only (MBI_BEHAVIOR = 0): nothing here carries a size, order, price target or stop.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TRADING_DAYS = 252
FINVIZ_CACHE_REL = "data/state/ticker_enrichment_cache.json"
POSITIONING_FIELDS = (
    "inst_trans_pct",
    "insider_trans_pct",
    "short_float_pct",
    "sma20_pct",
    "sma50_pct",
    "sma200_pct",
    "perf_week_pct",
    "perf_month_pct",
    "rvol",
)


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _parse(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=ET)
    if isinstance(ts, str) and ts:
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=ET)
    return None


def _latest_per_symbol(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = r.get("symbol")
        t = _parse(r.get("as_of"))
        if not s or t is None:
            continue
        if s not in out or t > _parse(out[s]["as_of"]):
            out[s] = r
    return out


def _iv(v: Any) -> float | None:
    x = _f(v)
    if x is None or x <= 0:
        return None
    return x / 100.0 if x > 3 else x  # snapshots store percent (23.7); tolerate a fraction (0.237)


def implied_moves(
    snapshot_rows: Iterable[dict[str, Any]], *, sessions: int, dq_ratio: float = 1.8, dq_min_history: int = 5
) -> dict[str, dict[str, Any]]:
    """{symbol: {move_pct, move_abs, atm_iv, underlying, sessions, as_of, source, dq_flags}} from the newest snapshot."""
    if sessions <= 0:
        raise ValueError("sessions must be positive")
    rows = list(snapshot_rows)
    hist: dict[str, list[tuple[datetime, float]]] = {}
    for r in rows:
        t, iv = _parse(r.get("as_of")), _iv(r.get("atm_iv"))
        if r.get("symbol") and t is not None and iv is not None:
            hist.setdefault(r["symbol"], []).append((t, iv))
    out: dict[str, dict[str, Any]] = {}
    for s, r in _latest_per_symbol(rows).items():
        iv, px = _iv(r.get("atm_iv")), _f(r.get("underlying_price"))
        if iv is None or px is None or px <= 0:
            continue
        newest = _parse(r.get("as_of"))
        prior = sorted(v for t, v in hist.get(s, []) if t < newest)
        flags: list[str] = []
        if len(prior) >= dq_min_history:
            med = prior[len(prior) // 2]
            ratio = iv / med if med else None
            if ratio is not None and (ratio > dq_ratio or ratio < 1.0 / dq_ratio):
                flags.append(f"iv_out_of_line:{iv:.3f}_vs_median_{med:.3f}")
        else:
            flags.append("iv_history_short")
        pct = iv * math.sqrt(sessions / TRADING_DAYS) * 100.0
        out[s] = {
            "move_pct": round(pct, 2),
            "move_abs": round(px * pct / 100.0, 4),
            "atm_iv": round(iv, 4),
            "underlying": px,
            "sessions": sessions,
            "as_of": r.get("as_of"),
            "source": "option_chain_snapshots(atm_iv)",
            "dq_flags": flags,
        }
    return out


def chain_daily_closes(snapshot_rows: Iterable[dict[str, Any]], *, window_minutes: int = 15) -> list[dict[str, Any]]:
    """Provisional daily closes: the EARLIEST snapshot inside [close, close + window] on an NYSE trading day."""
    from scripts.lib.market_risk import sessions as _sess

    best: dict[tuple[str, str], dict[str, Any]] = {}
    for r in snapshot_rows:
        s, px, t = r.get("symbol"), _f(r.get("underlying_price")), _parse(r.get("as_of"))
        if not s or px is None or px <= 0 or t is None:
            continue
        local = t.astimezone(ET)
        d = local.date()
        if not _sess.is_trading_day(d):
            continue  # weekend / holiday runs never make a close
        open_at = datetime.combine(d, _sess.close_time(d), tzinfo=ET)
        if not (open_at <= local <= open_at + timedelta(minutes=window_minutes)):
            continue  # intraday or later after-hours prints are not a close
        key = (s, d.isoformat())
        if key not in best or t < _parse(best[key]["as_of"]):
            best[key] = {
                "symbol": s,
                "session_date": key[1],
                "close": px,
                "as_of": r.get("as_of"),
                "source": "provisional_chain_snapshot",
            }
    return sorted(best.values(), key=lambda x: (x["symbol"], x["session_date"]))


def finviz_positioning(
    symbols: Iterable[str], *, end: datetime, root: Path | None = None, path: Path | None = None
) -> dict[str, dict[str, Any]]:
    """{symbol: {fields…, as_of, source}} from the Finviz enrichment cache, rows cached at or before ``end`` only."""
    if path is None:
        if root is None:
            from scripts.lib.persistent_state_root import good_persistent_root

            root = good_persistent_root()
        path = Path(root) / FINVIZ_CACHE_REL
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:  # unreadable cache is a visible gap, not an empty answer
        raise RuntimeError(f"finviz enrichment cache unreadable: {type(exc).__name__}") from exc
    items = doc.get("tickers", doc) if isinstance(doc, dict) else {}
    end_aware = end if end.tzinfo else end.replace(tzinfo=ET)
    out: dict[str, dict[str, Any]] = {}
    for s in symbols:
        r = items.get(s) if isinstance(items, dict) else None
        if not isinstance(r, dict):
            continue
        cached = _parse(r.get("cached_at"))
        hot = _parse(r.get("hot_cached_at"))
        known_at = max(t for t in (cached, hot) if t is not None) if (cached or hot) else None
        if cached is None or known_at is None or known_at > end_aware:
            continue
        fields = {k: _f(r.get(k)) for k in POSITIONING_FIELDS}
        if all(v is None for v in fields.values()):
            continue
        out[s] = {**fields, "as_of": known_at.isoformat(), "source": "finviz_enrichment_cache"}
    return out
