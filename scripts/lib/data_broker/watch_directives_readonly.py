"""Injected ticker-directive read core of the registered watch_intelligence projection.

The facade retains its optional DB-adapter behavior; scheduled read-only consumers
supply their already READ ONLY query callable here. One SQL/result implementation.
"""

from __future__ import annotations

from typing import Any


ACTIVE_TICKER_DIRECTIVES_SQL = """
            SELECT DISTINCT ON (UPPER(TRIM(spec->>'symbol')))
                   UPPER(TRIM(spec->>'symbol')) AS symbol, id, label, rationale,
                   trade_ai_enabled, hermes_enabled, created_at, updated_at
              FROM watch_directives
             WHERE status = 'active' AND kind = 'ticker' AND COALESCE(TRIM(spec->>'symbol'), '') <> ''
             ORDER BY UPPER(TRIM(spec->>'symbol')), created_at DESC, id DESC
            """


def active_ticker_directives(*, db_query: Any, strict: bool = False) -> list[dict[str, Any]]:
    """Read active ticker directives through the caller's injected query only."""
    if not callable(db_query):
        raise TypeError("an injected read-only query callable is required")
    try:
        rows = db_query(ACTIVE_TICKER_DIRECTIVES_SQL)
    except Exception:
        if strict:
            raise
        return []
    out = [dict(r) for r in rows or []]
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out
