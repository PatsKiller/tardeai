"""Run history for the options chain snapshot: one row per symbol per run, beside the latest-of-day table.

``option_chain_snapshots`` keeps one row per (as_of, symbol) and is upserted, so the 17:35 ET run replaces the
10:00 ET reading. ``option_chain_snapshot_runs`` (migrations/2026_10_31_option_chain_snapshot_runs.sql) keeps both.
Written by the same writer, scripts/options_chain_snapshot.py, in the same transaction. Until the migration is
applied the writer says so once per run and carries on writing the daily table exactly as before.

Read-only toward providers; no sender; advisory data (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TABLE = "option_chain_snapshot_runs"
FIELDS = (
    "put_oi",
    "call_oi",
    "put_vol",
    "call_vol",
    "pc_oi_ratio",
    "pc_vol_ratio",
    "atm_iv",
    "skew25",
    "underlying_price",
)


def slot_et(now: datetime | None = None) -> tuple[str, str]:
    """(as_of ET date ISO, 'HH:MM' ET) of a run. A naive ``now`` is taken as UTC."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    et = now.astimezone(ET)
    return et.date().isoformat(), et.strftime("%H:%M")


def table_present(cur) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (TABLE,))
    row = cur.fetchone()
    return bool(row and row[0])


def record_run(cur, symbol: str, agg: dict, *, as_of: str, slot: str) -> None:
    """Append one run row. A rerun in the same minute is a no-op (primary key as_of, slot_et, symbol)."""
    cols = ", ".join(FIELDS)
    marks = ", ".join(["%s"] * len(FIELDS))
    cur.execute(
        f"INSERT INTO {TABLE} (as_of, slot_et, symbol, {cols}) VALUES (%s, %s, %s, {marks}) "
        "ON CONFLICT (as_of, slot_et, symbol) DO NOTHING",
        (as_of, slot, symbol, *[agg.get(f) for f in FIELDS]),
    )
