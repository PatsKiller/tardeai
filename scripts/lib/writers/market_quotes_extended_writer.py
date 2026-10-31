"""The one write path for ``market_quotes_extended`` (registry domain ``quote_extended_session``).

Extended-session prints live in their own table so they can never become anyone's "latest quote": ``market_quotes``
is read newest-row-first by the data broker, the repricer, stop checks, watch alerts and ~15 more consumers with no
source filter (review of #2384). Rows are idempotent on (symbol, bar_start, feed). AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import math
from typing import Any

TABLE = "market_quotes_extended"
WRITTEN_BY = "scripts/lib/writers/market_quotes_extended_writer.py"
COLUMNS: tuple[str, ...] = (
    "symbol",
    "session",
    "session_date",
    "bar_start",
    "bar_end",
    "price",
    "volume",
    "reference_close",
    "reference_date",
    "reference_basis",
    "change_pct",
    "feed",
)
SESSIONS = frozenset({"premarket", "afterhours"})
INSERT_SQL = (
    f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))}) "
    "ON CONFLICT (symbol, bar_start, feed) DO NOTHING"
)


def validate(row: dict[str, Any]) -> str | None:
    """None when the row is writable, else the reason it is rejected."""
    missing = [c for c in COLUMNS if c != "volume" and row.get(c) in (None, "")]
    if missing:
        return f"missing {','.join(missing)}"
    if row["session"] not in SESSIONS:
        return f"session {row['session']!r}"
    for col in ("price", "reference_close"):
        v = row[col]
        if not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            return f"{col} {v!r}"
    if row["bar_end"] <= row["bar_start"]:
        return "bar_end not after bar_start"
    return None


def write_extended_quotes(cur: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    accepted, rejected = 0, []
    for r in rows:
        why = validate(r)
        if why:
            rejected.append({"symbol": r.get("symbol"), "reason": why})
            continue
        cur.execute(INSERT_SQL, [r.get(c) for c in COLUMNS])
        accepted += int(getattr(cur, "rowcount", 1) or 0)
    return {
        "table": TABLE,
        "written_by": WRITTEN_BY,
        "attempted": len(rows),
        "inserted": accepted,
        "rejected": rejected,
    }
