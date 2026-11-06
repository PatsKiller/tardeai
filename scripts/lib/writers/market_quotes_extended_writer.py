"""The one write path for ``market_quotes_extended`` (registry domain ``quote_extended_session``).

Extended-session prints live in their own table so they can never become anyone's "latest quote": ``market_quotes``
is read newest-row-first by the data broker, the repricer, stop checks, watch alerts and ~15 more consumers with no
source filter (review of #2384). Rows are idempotent on (symbol, bar_start, feed). AUTHORITY: READ_ONLY_ADVISORY.

Sessions (migrations/2026_10_31_market_quotes_extended_overnight.sql): ``premarket`` / ``afterhours`` (#2384) and
``overnight`` / ``futures_open`` (scripts/lib/overnight_session.py). An overnight or futures-open row must carry the
session and trading date that its ``bar_end`` (the trade instant) labels. It may store a level without a reference
(reference_close, reference_date and change_pct all None), but never a partial one. When it carries a reference,
that reference is the close of the trading day before its trading date.
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
SESSIONS = frozenset({"premarket", "afterhours", "overnight", "futures_open"})
LEVEL_ONLY_SESSIONS = frozenset({"overnight", "futures_open"})  # may store a level with no reference (never a guess)
REFERENCE_COLUMNS = ("reference_close", "reference_date", "change_pct")
INSERT_SQL = (
    "INSERT INTO market_quotes_extended (symbol, session, session_date, bar_start, bar_end, price, volume, "
    "reference_close, reference_date, reference_basis, change_pct, feed) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (symbol, bar_start, feed) DO NOTHING"
)


def _overnight():
    try:
        from scripts.lib import overnight_session as ovn
    except ImportError:  # scripts/ on sys.path (cron entries)
        from lib import overnight_session as ovn  # type: ignore[no-redef]
    return ovn


def _overnight_contract(row: dict[str, Any]) -> str | None:
    """The session/date labelling of an overnight or futures-open row, checked against its trade instant."""
    import json
    from pathlib import Path

    ovn = _overnight()
    cfg = json.loads((Path(__file__).resolve().parents[3] / "config" / "market_quotes_extended.json").read_text())
    end = row["bar_end"]
    if getattr(end, "tzinfo", None) is None:
        return "bar_end not timezone-aware"
    got = ovn.label(end, cfg, asset_type="FUTURE" if row["session"] == ovn.FUTURES_OPEN else "")
    want = (row["session"], row["session_date"])
    if got is None or got[0] != want[0]:
        return f"session {row['session']!r} does not contain bar_end {end.isoformat()}"
    if str(got[1]) != str(want[1]):
        return f"session_date {want[1]} is not the trading date {got[1]} of that {want[0]}"
    if row.get("reference_close") is not None and str(row["reference_date"]) != str(ovn.reference_date(got[1])):
        return f"reference_date {row['reference_date']} is not the last session {ovn.reference_date(got[1])} before it"
    return None


def validate(row: dict[str, Any]) -> str | None:
    """None when the row is writable, else the reason it is rejected."""
    level_only = row.get("session") in LEVEL_ONLY_SESSIONS and all(row.get(c) is None for c in REFERENCE_COLUMNS)
    optional = {"volume", *REFERENCE_COLUMNS} if level_only else {"volume"}
    missing = [c for c in COLUMNS if c not in optional and row.get(c) in (None, "")]
    if missing:
        return f"missing {','.join(missing)}"
    if row["session"] not in SESSIONS:
        return f"session {row['session']!r}"
    for col in ("price",) if level_only else ("price", "reference_close"):
        v = row[col]
        if not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            return f"{col} {v!r}"
    if row["bar_end"] <= row["bar_start"]:
        return "bar_end not after bar_start"
    if row["session"] in LEVEL_ONLY_SESSIONS:
        return _overnight_contract(row)
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
