"""LQ-20261107-126 — the daily-close cache must keep the LAST quote of each session date.

ANCHOR: HERMES_OUTCOME_GRADER_CLOSE_CACHE_20261107

Hermetic: no database. A recording cursor captures the exact SQL `refresh_close_cache` sends, and the
tests assert the statement's ordering, which is where the defect lives.

The defect (2026-11-07). The statement was

    SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
           UPPER(symbol), fetched_at::date, price, 'market_quotes'
    FROM market_quotes
    ...
    ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC

PostgreSQL resolves an *unqualified* ORDER BY name against the SELECT-list output names first, and a
cast expression takes its name from its argument — so the third output column here is itself named
`fetched_at`. The `fetched_at DESC` key therefore bound to `fetched_at::date`, the same key that leads
the ORDER BY, which is constant inside a DISTINCT ON group. The DESC key vanished (EXPLAIN showed
`Sort Key: ((market_quotes.fetched_at)::date)` with no second key), and each day's row became an
arbitrary quote of that day — usually the first one the scan delivered.

Measured live on 2026-11-07 through the application's own connection: the old statement returned
XLK 2026-11-06 = 161.75 (a 07:15 print) where the true last quote was 164.8; repeated runs of the same
statement returned different prices for the same day. The fix qualifies the reference and adds an id
tiebreak, and buckets the day in the New York session so the result does not follow the server's
TimeZone setting.

SUPERSEDED IN PART by LQ-20261107-275 (tests/test_hermes_outcome_grader_post_close_lq275_20261107.py).
"The last quote of the day" was itself not a close: the poller runs past the bell, so it is an
after-hours trade (XLK 2026-11-05: 161.75 vs the official 162.45). The refresh now inserts from the data
broker's ``session_close`` projection, which takes a close only from quotes fetched after the bell and
orders the chosen quote ASC (first after the close), not DESC. What LQ-126 established still holds and is
pinned here: every quote-timestamp reference is table-qualified, the day bucket is the New York date, and
the detector still flags the legacy statement.
"""

from __future__ import annotations

import importlib
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SESSION_DATE = "(market_quotes.fetched_at AT TIME ZONE 'America/New_York')::date"

# An unqualified (or aliased-without-table) quote-timestamp reference, e.g. `fetched_at` in
# `ORDER BY …, fetched_at DESC`. Table-qualified references (`market_quotes.fetched_at`) are excluded.
BARE_QUOTE_TS = re.compile(r"(?<![\w.])fetched_at\b")


class RecordingCursor:
    """Records (sql, params); never touches a database."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchall(self):
        return []


def _upsert_call():
    mod = importlib.import_module("hermes_outcome_grader")
    cur = RecordingCursor()
    mod.refresh_close_cache(cur, {"close_cache_refresh_days": 4}, today=date(2026, 11, 9))
    return cur.calls[0]


def _order_by(sql: str) -> str:
    """The ORDER BY clause of a legacy close-cache upsert, up to ON CONFLICT."""
    after = sql.split("ORDER BY", 1)[1]
    return after.split("ON CONFLICT", 1)[0]


def _bare_quote_ts_in_order_by(sql: str) -> list[str]:
    """Quote-timestamp keys in the ORDER BY that PostgreSQL would resolve against the SELECT list."""
    return BARE_QUOTE_TS.findall(_order_by(sql).replace("market_quotes.fetched_at", ""))


def test_every_quote_timestamp_reference_is_table_qualified():
    sql, _ = _upsert_call()
    assert "market_quotes.fetched_at" in sql
    assert BARE_QUOTE_TS.findall(sql.replace("market_quotes.fetched_at", "")) == []


def test_day_bucket_is_the_new_york_session_date():
    sql, _ = _upsert_call()
    assert SESSION_DATE in sql
    assert "fetched_at::date" not in sql


def test_the_last_quote_of_the_day_rule_is_gone():
    sql, _ = _upsert_call()
    assert "fetched_at DESC" not in sql and "quote_at DESC" not in sql


# --- the detector itself must catch the statement as it was ------------------------------------------

def test_the_detector_flags_the_legacy_statement():
    """A no-op self-check: if this fails, the tests above prove nothing."""
    legacy = """INSERT INTO daily_close_cache (symbol, price_date, close_price, source)
                SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
                       UPPER(symbol), fetched_at::date, price, 'market_quotes'
                FROM market_quotes
                WHERE fetched_at >= NOW() - make_interval(days => %s)
                AND price IS NOT NULL AND price > 0
                ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC
                ON CONFLICT (symbol, price_date) DO UPDATE SET
                  close_price = EXCLUDED.close_price, source = EXCLUDED.source"""
    assert "market_quotes.fetched_at DESC" not in _order_by(legacy)
    assert len(_bare_quote_ts_in_order_by(legacy)) >= 1
    assert "fetched_at::date" in legacy and "fetched_at DESC" in legacy
