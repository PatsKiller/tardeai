"""Additive /api/v3/watchlist/intelligence* — read-only shadow APIs.

Page load and these GETs cause zero provider calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def get_list(query: dict | None = None) -> dict[str, Any]:
    from lib.watchlist_intelligence import list_intelligence

    q = query or {}
    limit = int(q.get("limit") or 24)
    offset = int(q.get("offset") or 0)
    priority = str(q.get("priority") or "1").lower() not in ("0", "false", "no")
    symbols = None
    if q.get("symbols"):
        symbols = [s.strip().upper() for s in str(q["symbols"]).split(",") if s.strip()]
    return list_intelligence(
        symbols=symbols,
        limit=min(max(limit, 1), 100),
        offset=max(offset, 0),
        priority_only=priority and not symbols,
    )


def get_detail(symbol: str) -> dict[str, Any]:
    from lib.watchlist_intelligence import detail_intelligence
    return detail_intelligence(symbol)


def get_reviews(symbol: str) -> dict[str, Any]:
    from lib.watchlist_intelligence import reviews_intelligence
    return reviews_intelligence(symbol)
