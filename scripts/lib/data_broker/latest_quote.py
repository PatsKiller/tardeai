"""Latest Quote — Data Broker read model: the newest stored quote per symbol, with its age.

Operator decision 2026-10-10 ~17:45 ET (CONSOLIDATION_PLAN.md §D.7, "add a latest_quote projection
now"). Domain ``quote_price`` in ``config/data_source_authority.json``: store ``market_quotes``,
single writer ``scripts/lib/writers/market_quotes_writer.py``.

Why a projection and not another query. Every "latest price for these symbols" read in the estate
was ``SELECT DISTINCT ON (upper(symbol)) ... WHERE upper(symbol) = ANY(...)``. The only useful
index is ``idx_market_quotes_symbol_fetched_at_desc (symbol, fetched_at DESC)``, and ``upper(symbol)``
cannot use it, so each read is a sequential scan of an append-only table (3.47M rows; 860k seq
scans and 1.69 trillion tuples read cumulatively, API_OVERLAP_CONSOLIDATION.md §1.3). Measured
2026-10-10, five symbols: DISTINCT ON + upper() 96.2 ms (1,165,228 rows removed by filter);
the LATERAL index probe below 0.084 ms. Symbols are stored upper-case (0 non-upper rows in the
last 3 days, measured the same day), so exact-match on the upper-cased input loses nothing.

What it returns. Per symbol the newest row (whatever its age) with ``as_of`` / ``age_seconds`` /
``stale`` against the caller's bound, plus a ``BrokerReadEnvelope@v1`` over the batch. A stale row
is still returned, labelled: the domain's declared ``no_coverage`` is
``last_price_with_age_and_source``. Whether a stale symbol deserves a provider call is the
caller's decision (``market_quote_provider.get_best_quote(..., max_age_seconds=...)``); this
module never calls a provider and never writes.

The retirement of the second quote store (``market_quote_snapshots``, cron L92/L128) is planned in
``docs/ops/QUOTE_SNAPSHOTS_RETIREMENT_PLAN_2026-10-10.md`` and not executed here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from lib.data_broker.envelope import envelope

DOMAIN = "quote_price"
PROJECTION = "latest_quote"
TABLE = "market_quotes"
WRITER = "scripts/lib/writers/market_quotes_writer.py"
#: quote_price.stale_after_hours (0.25 h) in config/data_source_authority.json
DEFAULT_MAX_AGE_SECONDS = 900.0

#: One index probe per symbol on (symbol, fetched_at DESC). No upper(): symbols are stored upper.
LATEST_SQL = """
SELECT s.sym AS symbol, q.price, q.prev_close, q.day_change_pct, q.volume, q.fetched_at, q.source
FROM unnest(%s::text[]) AS s(sym)
CROSS JOIN LATERAL (
    SELECT m.price, m.prev_close, m.day_change_pct, m.volume, m.fetched_at, m.source
    FROM market_quotes m
    WHERE m.symbol = s.sym AND m.price IS NOT NULL
    ORDER BY m.fetched_at DESC
    LIMIT 1
) q
"""


def _norm(symbols: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols or []:
        sym = str(s or "").upper().strip()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # timestamptz read without tz info is UTC
    return dt.astimezone(timezone.utc)


def _f(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _row_get(row: Any, key: str, idx: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[idx]
    except (IndexError, KeyError, TypeError):
        return None


def get_latest_quotes(
    db_query: Callable[..., Any],
    symbols: Iterable[Any],
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Newest stored quote per symbol, with freshness against ``max_age_seconds``.

    ``db_query(sql, params)`` returns rows (dicts, or tuples in the SELECT order). Returns::

        {"ok": bool, "provider_calls": 0,
         "symbols": {SYM: {"price", "prev_close", "chg_pct", "volume", "as_of", "age_seconds",
                           "provider", "source", "stale"}},
         "fresh": [SYM, ...], "stale_or_missing": [SYM, ...],
         <BrokerReadEnvelope@v1 over the newest as_of read>}

    A symbol with no stored row is absent from ``symbols`` and listed in ``stale_or_missing``.
    A failed read is ``ok: False`` with ``error`` and every symbol in ``stale_or_missing``.
    """
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    syms = _norm(symbols)
    per: dict[str, dict[str, Any]] = {}
    fresh: list[str] = []
    stale_or_missing: list[str] = []
    newest: datetime | None = None
    error: str | None = None
    rows: list[Any] = []
    if syms:
        try:
            rows = list(db_query(LATEST_SQL, (syms,)) or [])
        except Exception as exc:  # noqa: BLE001 - a failed read is reported, never raised
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
    for row in rows:
        sym = str(_row_get(row, "symbol", 0) or "").upper()
        price = _f(_row_get(row, "price", 1))
        dt = _as_utc(_row_get(row, "fetched_at", 5))
        if not sym or sym not in syms or price is None:
            continue
        age = max(0.0, (ref - dt).total_seconds()) if dt else None
        provider = str(_row_get(row, "source", 6) or "") or None
        per[sym] = {
            "price": price,
            "prev_close": _f(_row_get(row, "prev_close", 2)),
            "chg_pct": _f(_row_get(row, "day_change_pct", 3)),
            "volume": _row_get(row, "volume", 4),
            "as_of": dt.isoformat() if dt else None,
            "age_seconds": round(age, 1) if age is not None else None,
            "provider": provider,
            "source": f"data_broker.{PROJECTION}:{provider or TABLE}",
            "stale": age is None or age > float(max_age_seconds),
        }
        if dt and (newest is None or dt > newest):
            newest = dt
    for sym in syms:
        rec = per.get(sym)
        (fresh if rec and not rec["stale"] else stale_or_missing).append(sym)
    out: dict[str, Any] = {
        "ok": error is None,
        "provider_calls": 0,
        "symbols": per,
        "fresh": fresh,
        "stale_or_missing": stale_or_missing,
    }
    if error:
        out["error"] = error
    out.update(
        envelope(
            DOMAIN,
            newest,
            now=ref,
            stale_after_hours=float(max_age_seconds) / 3600.0,
            source={"table": TABLE, "writer": WRITER, "projection": PROJECTION},
        )
    )
    return out


def get_latest_quote(db_query: Callable[..., Any], symbol: Any, **kwargs: Any) -> dict[str, Any] | None:
    """Single-symbol convenience: the symbol's row from :func:`get_latest_quotes`, or None."""
    batch = get_latest_quotes(db_query, [symbol], **kwargs)
    return batch["symbols"].get(str(symbol or "").upper().strip())
