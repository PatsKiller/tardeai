"""CatalystSymbolImpact@v1 — the operator-facing reader for `catalyst_symbol_impact` (LQ-20261107-135).

`catalyst_symbol_impact_writer.py` has been writing this table on every run (126 rows on 2026-11-06;
10,306 rows since 2026-09-15) and, before this module, nothing operator-facing ever read it. The only
readers were `news_symbol_guard` (purge) and `lib/catalyst_graph` — so an accurate per-symbol answer to
"what did this catalyst mean for this name" existed and could not be seen.

One row per (catalyst_event, symbol), written only for names Trade-AI tracks:

  price_at_event        last close on or before the event day (ticker_prices)
  expected_direction    UP / DOWN / NEUTRAL derived from the catalyst type
  expected_magnitude    the event's impact_score when present (not a forecast)
  portfolio_impact_pct  the holding's weight in the portfolio (0 when not held)

READ_ONLY_ADVISORY. No mutation, no provider call, no broker call, no financial action. The reader
never invents a row: an empty window says `no_rows` and still reports when the writer last recorded
something for that symbol, because "no catalyst impact recorded" is not the same statement as
"nothing happened".
"""

from __future__ import annotations

import re
from typing import Any, Callable

SCHEMA = "CatalystSymbolImpact@v1"

AUTHORITY = {
    "authority": "READ_ONLY_ADVISORY",
    "mutation": False,
    "financial_action": False,
    "service_control": False,
    "provider_call": False,
    "broker_call": False,
}

DEFAULT_DAYS = 90
DEFAULT_LIMIT = 25
MAX_LIMIT = 200
MAX_DAYS = 3650

_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")

_ROWS_SQL = """
SELECT i.id, upper(i.symbol) AS symbol, i.strategy_type, i.expected_direction,
       i.expected_magnitude, i.price_at_event, i.portfolio_impact_pct, i.created_at,
       e.catalyst_type, e.headline, e.severity, e.impact_score, e.source_url,
       COALESCE(e.published_at, e.created_at) AS event_at
  FROM catalyst_symbol_impact i
  JOIN catalyst_events e ON e.id = i.catalyst_event_id
 WHERE (%s::text IS NULL OR upper(i.symbol) = %s)
   AND i.created_at >= now() - make_interval(days => %s)
 ORDER BY i.created_at DESC, i.id DESC
 LIMIT %s
"""

_LAST_SQL = """
SELECT max(created_at) AS last_row_at, count(*) AS rows_written
  FROM catalyst_symbol_impact
 WHERE upper(symbol) = %s
"""


class BadRequest(ValueError):
    """A query parameter the reader refuses. The handler maps this to 400, never to a silent default."""


def _db_callable() -> Callable[..., Any]:
    """The same DB callable api_v2 uses (`db_adapter._execute`), imported lazily."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]

    def _q(sql, params=None, fetch="all"):
        if str(root / "scripts") not in sys.path:
            sys.path.insert(0, str(root / "scripts"))
        from db_adapter import USE_DB, _execute  # noqa: PLC0415

        if not USE_DB:
            raise RuntimeError("database disabled (USE_DB false)")
        return _execute(sql, params, fetch=fetch)

    return _q


def _clean_symbol(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    if not _SYMBOL_RE.match(s):
        raise BadRequest(f"symbol {raw!r} is not a ticker (A-Z, 0-9, '.', '-' — max 12 chars)")
    return s


def _clean_int(raw: Any, default: int, lo: int, hi: int, field: str) -> int:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        raise BadRequest(f"{field} must be an integer (got {raw!r})") from None
    if v < lo or v > hi:
        raise BadRequest(f"{field} must be between {lo} and {hi} (got {v})")
    return v


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _row(r: dict[str, Any]) -> dict[str, Any]:
    direction = r.get("expected_direction")
    return {
        "id": r.get("id"),
        "symbol": r.get("symbol"),
        "strategy_type": r.get("strategy_type"),
        "catalyst_type": r.get("catalyst_type"),
        "headline": r.get("headline"),
        "severity": r.get("severity"),
        "expected_direction": (str(direction).strip().upper() if direction else None),
        "expected_magnitude": _f(r.get("expected_magnitude")),
        "price_at_event": _f(r.get("price_at_event")),
        "portfolio_impact_pct": _f(r.get("portfolio_impact_pct")),
        "impact_score": _f(r.get("impact_score")),
        "source_url": r.get("source_url"),
        "event_at": _ts(r.get("event_at")),
        "recorded_at": _ts(r.get("created_at")),
    }


def build(
    symbol: Any = None,
    days: Any = DEFAULT_DAYS,
    limit: Any = DEFAULT_LIMIT,
    db: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Rows for one symbol (or the most recent across all symbols when `symbol` is omitted)."""
    sym = _clean_symbol(symbol)
    window = _clean_int(days, DEFAULT_DAYS, 1, MAX_DAYS, "days")
    cap = _clean_int(limit, DEFAULT_LIMIT, 1, MAX_LIMIT, "limit")
    q = db or _db_callable()

    raw = q(_ROWS_SQL, (sym, sym, window, cap), fetch="all") or []
    rows = [_row(dict(r)) for r in raw]

    last_row_at = None
    rows_written = None
    if sym:
        last = q(_LAST_SQL, (sym,), fetch="one")
        if last:
            last = dict(last)
            last_row_at = _ts(last.get("last_row_at"))
            try:
                rows_written = int(last.get("rows_written") or 0)
            except (TypeError, ValueError):
                rows_written = None

    if rows:
        status = "ok"
        note = None
    elif sym and rows_written:
        # The distinction that matters: the symbol is tracked and has rows, just none in this window.
        status = "no_rows_in_window"
        note = (
            f"no catalyst impact recorded for {sym} in the last {window} days; "
            f"the writer has recorded {rows_written} row(s), most recently {last_row_at or 'unknown'}"
        )
    else:
        status = "no_rows"
        note = f"the writer has recorded no catalyst impact for {sym}" if sym else "the table has no rows yet"

    return {
        "ok": True,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "symbol": sym,
        "days": window,
        "limit": cap,
        "status": status,
        "count": len(rows),
        "last_row_at": last_row_at,
        "rows_written_total": rows_written,
        "note": note,
        "rows": rows,
    }
