"""Read side of the Watchlist "Screener Finds" lane (LQ-20261107-2487).

Why: ``GET /api/v2/screener-finds/candidates`` and ``GET /api/v2/watchlist/items?lane=screener_finds`` called
``_sync_all_screener_find_pins()`` before reading. That upserts EVERY row of ``screener_find_pins`` (275 rows, 2
statements) on each GET, stamping ``auto_research_at = now() + k µs`` and re-deriving ``active`` / ``cio_recommendation``;
``_wl_items`` also ran ``CREATE TABLE IF NOT EXISTS`` on every call. A GET must not write, and a "last researched" column
must not move because a page was opened (measured 2026-11-12: all 275 rows carry today's 13:03:57 stamp).

This module is the read-only replacement: one SELECT, no DDL, no write. ``active`` is DERIVED on read from the same CIO
verdict the sync used (``watchlist_final_synthesis`` then ``watchlist_research_cards``), so a pin shows while the verdict
is buy-side exactly as before, with no writer in the request path. ``stored_active`` is returned beside it so a drift
between the stored flag (read by the priority queries) and the live verdict is visible instead of silently repaired.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

BUY_SIDE = frozenset({"BUY", "STRONG_BUY", "ADD", "ADD_ON_PULLBACK"})

PINS_SQL = """
SELECT p.symbol, p.pinned_at, p.auto_research_at, p.discovery_reason, p.strategy_type, p.brief_snippet,
       p.cio_recommendation AS stored_cio_recommendation, p.active AS stored_active,
       cio.rec AS live_cio_recommendation
  FROM screener_find_pins p
  LEFT JOIN LATERAL (
        SELECT upper(btrim(COALESCE(fs.recommendation, rc.latest_recommendation, ''))) AS rec
          FROM watchlist_items wi
          LEFT JOIN watchlist_final_synthesis fs ON upper(fs.symbol) = upper(wi.symbol)
          LEFT JOIN watchlist_research_cards rc ON rc.symbol = wi.symbol
         WHERE upper(wi.symbol) = upper(p.symbol) AND wi.status <> 'removed'
         LIMIT 1) cio ON true
 ORDER BY p.auto_research_at DESC NULLS LAST, p.pinned_at DESC, p.symbol
"""


def read_pins(query: Callable[..., Any]) -> Optional[list[dict[str, Any]]]:
    """Every pin with its live CIO verdict, newest research first; None when the table could not be read."""
    rows = query(PINS_SQL)
    if rows is None:
        return None
    out = []
    for r in rows:
        live = str(r.get("live_cio_recommendation") or "").upper().strip()
        out.append(
            {
                "symbol": r["symbol"],
                "pinned_at": r.get("pinned_at"),
                "auto_research_at": r.get("auto_research_at"),
                "discovery_reason": r.get("discovery_reason"),
                "strategy_type": r.get("strategy_type"),
                "brief_snippet": r.get("brief_snippet"),
                "cio_recommendation": live or None,
                "active": live in BUY_SIDE,
                "stored_active": bool(r.get("stored_active")),
                "stored_cio_recommendation": r.get("stored_cio_recommendation"),
            }
        )
    return out


def active_pins(query: Callable[..., Any]) -> list[dict[str, Any]]:
    """The buy-side pins (what the lane shows), same order as ``read_pins``. [] when unreadable (never a write)."""
    return [p for p in (read_pins(query) or []) if p["active"]]


def drifted(pins: list[dict[str, Any]]) -> list[str]:
    """Symbols whose stored ``active`` flag disagrees with the live verdict (the writer lane's work list)."""
    return [p["symbol"] for p in pins if p["active"] != p["stored_active"]]
