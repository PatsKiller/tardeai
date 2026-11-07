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
"""

from __future__ import annotations

import importlib
import re
import sys
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


def _upsert_call(cfg=None, backfill=False):
    mod = importlib.import_module("hermes_outcome_grader")
    cur = RecordingCursor()
    mod.refresh_close_cache(cur, {"close_cache_refresh_days": 4} if cfg is None else cfg,
                            backfill=backfill)
    sql, params = cur.calls[0]
    return sql, params


def _order_by(sql: str) -> str:
    """The ORDER BY clause of the close-cache upsert, up to ON CONFLICT."""
    after = sql.split("ORDER BY", 1)[1]
    return after.split("ON CONFLICT", 1)[0]


def _bare_quote_ts_in_order_by(sql: str) -> list[str]:
    """Quote-timestamp keys in the ORDER BY that PostgreSQL would resolve against the SELECT list."""
    return BARE_QUOTE_TS.findall(_order_by(sql).replace("market_quotes.fetched_at", ""))


# --- the ordering must be the quote time, not the day ------------------------------------------------

def test_order_by_sorts_by_the_quote_time_reference_that_cannot_bind_to_the_output_column():
    sql, _ = _upsert_call()
    assert "market_quotes.fetched_at DESC" in _order_by(sql)
    assert _bare_quote_ts_in_order_by(sql) == []


def test_order_by_ends_with_a_tiebreak_so_one_row_per_day_is_deterministic():
    order = _order_by(_upsert_call()[0]).strip()
    assert re.search(r"market_quotes\.fetched_at DESC,\s*market_quotes\.id DESC$", order), order


def test_backfill_uses_the_same_ordering():
    sql, params = _upsert_call(cfg={}, backfill=True)
    assert params is None
    assert "market_quotes.fetched_at DESC" in _order_by(sql)
    assert _bare_quote_ts_in_order_by(sql) == []


# --- the day bucket must not follow the server's TimeZone --------------------------------------------

def test_day_bucket_is_the_new_york_session_date_everywhere_it_appears():
    sql, _ = _upsert_call()
    # DISTINCT ON key, the inserted price_date, and the ORDER BY key must be the same expression.
    assert sql.count(SESSION_DATE) >= 3, sql
    assert "fetched_at::date" not in sql


def test_the_window_and_the_ordering_agree_on_the_column_they_filter():
    sql, params = _upsert_call()
    assert "market_quotes.fetched_at >= NOW() - make_interval(days => %s)" in sql
    assert params == (4,)
    assert sql.count("%s") == len(params)


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
