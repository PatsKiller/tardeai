"""Consumer-side skip for quarantined ticker_prices rows (G-PRICE-01).

The Stage B scrub copies corrupt bars into `ticker_prices_quarantine` before
removing them from the live table. G-PRICE-01 additionally requires price
readers used by CIO / research to honor that quarantine set: skip
(symbol, date) pairs even if a live row somehow remains (restore race,
partial apply, or a future "flag without scrub" mode).

Fail-soft: if the quarantine table is missing or unreadable, treat the set
as empty so price reads continue. Never DELETE from ticker_prices here.

AUTHORITY: READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
# Wired into price_db_sync + portfolio_price_cache (production consumers).
SCHEMA = "TickerPriceQuarantineSkip@v1"

_PAIR_SQL = "SELECT symbol, price_date FROM ticker_prices_quarantine"


def normalize_pair(symbol: Any, price_date: Any) -> tuple[str, str] | None:
    """Return (SYMBOL, YYYY-MM-DD) or None when either side is unusable."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    if isinstance(price_date, datetime):
        ds = price_date.date().isoformat()
    elif isinstance(price_date, date):
        ds = price_date.isoformat()
    else:
        ds = str(price_date or "").strip()
        if not ds:
            return None
        # Accept "2026-05-04 00:00:00+00" / ISO timestamps.
        ds = ds[:10]
    if len(ds) < 10:
        return None
    return sym, ds


def is_quarantined(symbol: Any, price_date: Any, quarantined: set[tuple[str, str]]) -> bool:
    pair = normalize_pair(symbol, price_date)
    if pair is None:
        return False
    return pair in quarantined


def quarantined_pairs(conn) -> set[tuple[str, str]]:
    """Load {(SYMBOL, YYYY-MM-DD), ...} from ticker_prices_quarantine.

    Fail-soft: missing table / any DB error → empty set (after rollback when
    possible so the caller's transaction is not left aborted).
    """
    if conn is None:
        return set()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(_PAIR_SQL)
        out: set[tuple[str, str]] = set()
        for symbol, price_date in cur.fetchall() or []:
            pair = normalize_pair(symbol, price_date)
            if pair is not None:
                out.add(pair)
        return out
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return set()
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass


def filter_prices(
    rows: Iterable[Any],
    quarantined: set[tuple[str, str]],
    *,
    symbol_key: Any = 0,
    date_key: Any = 1,
) -> list[Any]:
    """Drop rows whose (symbol, date) is in ``quarantined``.

    Supports:
    - sequence rows (tuple/list) indexed by ``symbol_key`` / ``date_key``
    - mapping rows with keys ``symbol`` + (``price_date`` | ``date`` | ``price_date_str``)
    """
    if not quarantined:
        return list(rows)

    kept: list[Any] = []
    for row in rows:
        sym: Any
        dt: Any
        if isinstance(row, Mapping):
            sym = row.get("symbol")
            dt = row.get("price_date", row.get("date", row.get("price_date_str")))
        elif isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
            try:
                sym = row[symbol_key]  # type: ignore[index]
                dt = row[date_key]  # type: ignore[index]
            except (IndexError, KeyError, TypeError):
                kept.append(row)
                continue
        else:
            kept.append(row)
            continue
        if is_quarantined(sym, dt, quarantined):
            continue
        kept.append(row)
    return kept


def filter_price_cache(
    cache: MutableMapping[str, Any] | Mapping[str, Any],
    quarantined: set[tuple[str, str]],
) -> dict[str, Any]:
    """Strip quarantined dates from a {symbol: {date_str: price}} cache.

    Meta keys (``_meta``, or any key starting with ``_``) are preserved.
    """
    if not quarantined or not cache:
        return dict(cache)

    out: dict[str, Any] = {}
    for sym, prices in cache.items():
        if str(sym).startswith("_") or not isinstance(prices, Mapping):
            out[sym] = prices
            continue
        kept: dict[str, Any] = {}
        for ds, price in prices.items():
            if is_quarantined(sym, ds, quarantined):
                continue
            kept[ds] = price
        out[sym] = kept
    return out


_CACHE: set[tuple[str, str]] | None = None
_CACHE_MONO: float = 0.0
_CACHE_TTL_S = 60.0


def clear_quarantine_cache() -> None:
    """Test / operator hook to drop the process-local quarantine cache."""
    global _CACHE, _CACHE_MONO
    _CACHE = None
    _CACHE_MONO = 0.0


def load_quarantined_pairs_failsoft(
    conn_factory=None,
    *,
    ttl_s: float = _CACHE_TTL_S,
    force: bool = False,
) -> set[tuple[str, str]]:
    """Convenience: open a connection (optional factory), load, close. Always fail-soft.

    Process-local cache (default 60s) avoids opening Postgres on every price
    lookup in hot paths like ``portfolio_price_cache.get_price``.
    """
    global _CACHE, _CACHE_MONO
    import time

    now = time.monotonic()
    if (
        not force
        and _CACHE is not None
        and ttl_s > 0
        and (now - _CACHE_MONO) < ttl_s
    ):
        return _CACHE

    conn = None
    try:
        if conn_factory is not None:
            conn = conn_factory()
        else:
            from price_db_sync import _get_conn  # type: ignore

            conn = _get_conn()
        pairs = quarantined_pairs(conn)
    except Exception:
        pairs = set()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    _CACHE = pairs
    _CACHE_MONO = now
    return pairs
