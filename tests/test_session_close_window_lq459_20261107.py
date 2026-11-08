"""LQ-20261107-459: the session close is the FIRST print at/after 16:00 inside a window.

LQ-406 taught the fill to write a session bar at all; it took "the close" to be the LAST quote of
the date. Measured read-only for 2026-11-06, the broker feed (``source=alpaca``) printed at
16:00:04 ET for every symbol in the sector universe — the consolidated close — and then refreshed
at 16:30:03 and 16:45:02. Taking the last print stored the refresh as the close:

| symbol | 16:00:04 print (close) | 16:45:02 print (stored) | error |
|---|---|---|---|
| XLF | 57.16 | 57.13 | 5.2 bp |
| SPY | 735.40 | 735.53 | 1.8 bp |
| XLK | 164.79 | 164.80 | 0.6 bp |

So the window is config (``config/session_close.json``), the selection is the first print inside
it, and a symbol with quotes that day but none inside the window is reported as
``no_close_print`` rather than being priced at its after-hours refresh.

These tests are config/SQL-level: the statement must say FIRST and must be bounded in ET, the
window must come from config, a broken config must fail closed, and the default (no window)
statement must stay byte-identical for every other caller. The 11-06 numbers are re-measured by
the dry run quoted in the DONE note, not here (that needs the DB).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.writers import ticker_prices_writer as tp  # noqa: E402
from scripts import price_db_sync as pds  # noqa: E402


def norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _write_cfg(tmp_path: Path, doc) -> Path:
    p = tmp_path / "session_close.json"
    p.write_text(json.dumps(doc) if not isinstance(doc, str) else doc, encoding="utf-8")
    return p


class RecCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((norm(sql), params))

    def fetchall(self):
        return []

    def close(self):
        pass


# ── the window is configuration ─────────────────────────────────────────────


def test_the_shipped_config_is_the_window_the_fill_uses():
    win = pds.session_close_window()
    assert (win.close.hour, win.close.minute) == (16, 0)
    assert win.minutes >= 1
    assert win.label == f"16:00-{win.end:%H:%M} ET"


def test_the_window_comes_from_config_not_from_code(tmp_path):
    """Two different configs must produce two different windows and two different statements."""
    five = pds.session_close_window(_write_cfg(tmp_path, {"close_time_et": "16:00",
                                                          "window_minutes": 5}))
    thirty = pds.session_close_window(_write_cfg(tmp_path, {"close_time_et": "16:00",
                                                            "window_minutes": 30}))
    assert (five.minutes, thirty.minutes) == (5, 30)
    assert five.label == "16:00-16:05 ET" and thirty.label == "16:00-16:30 ET"

    cur = RecCursor()
    pds.plan_session_closes(cur, date(2026, 11, 6), ["XLF"], window=five)
    assert cur.calls[0][1]["close"] == time(16, 0) and cur.calls[0][1]["end"] == time(16, 5)

    cur2 = RecCursor()
    pds.plan_session_closes(cur2, date(2026, 11, 6), ["XLF"], window=thirty)
    assert cur2.calls[0][1]["end"] == time(16, 30)


def test_an_earlier_close_time_is_honoured_too(tmp_path):
    """Nothing in the code may assume 16:00 — a half day closes earlier."""
    half = pds.session_close_window(_write_cfg(tmp_path, {"close_time_et": "13:00",
                                                          "window_minutes": 10}))
    assert half.label == "13:00-13:10 ET"


@pytest.mark.parametrize("doc", [
    {"close_time_et": "16:00", "window_minutes": 0},
    {"close_time_et": "16:00", "window_minutes": 500},
    {"close_time_et": "16:00"},
    {"window_minutes": 10},
    {"close_time_et": "4pm", "window_minutes": 10},
    "not json at all",
])
def test_a_broken_config_fails_closed(tmp_path, doc):
    """A price writer must not guess which print is a close."""
    with pytest.raises((ValueError, RuntimeError)):
        pds.session_close_window(_write_cfg(tmp_path, doc))


def test_a_missing_config_fails_closed(tmp_path):
    with pytest.raises(RuntimeError):
        pds.session_close_window(tmp_path / "absent.json")


# ── the selection is FIRST-in-window, bounded in ET ──────────────────────────


def test_the_plan_selects_the_first_print_inside_the_window():
    cur = RecCursor()
    pds.plan_session_closes(cur, date(2026, 11, 6), ["XLF"])
    sql, params = cur.calls[0]
    assert "fetched_at ASC" in sql and "fetched_at DESC" not in sql
    assert "DISTINCT ON (UPPER(symbol))" in sql
    assert sql.count("(fetched_at AT TIME ZONE 'America/New_York')::time") == 2
    assert ">= %(close)s" in sql and "< %(end)s" in sql
    assert params["close"] == time(16, 0) and params["end"] == time(16, 10)
    assert "day_q" in sql and "LEFT JOIN close_q" in sql   # a symbol without a close print survives


def test_the_session_resolver_asks_for_a_print_inside_the_window():
    cur = RecCursor()
    pds.resolve_session_close_date(cur, ["XLF"], today=date(2026, 11, 7))
    sql, params = cur.calls[0]
    assert "count(*) FILTER" in sql and "min(fetched_at) FILTER" in sql
    assert params["close"] == time(16, 0) and params["end"] == time(16, 10)


def test_the_write_takes_the_first_print_too():
    """The plan is a report; the INSERT is what lands in ticker_prices. Both must be FIRST."""
    sql = tp._quotes_sync_sql("AND UPPER(symbol) = ANY(%(syms)s)",
                              "\n AND fetched_at::date = %(session)s",
                              only_missing=True, close_window=(time(16, 0), time(16, 10)))
    assert "fetched_at ASC" in sql and "fetched_at DESC" not in sql
    assert ">= %(close_time)s" in sql and "<  %(close_end)s" in sql
    assert "ON CONFLICT (symbol, price_date) DO NOTHING" in sql


def test_every_other_caller_gets_the_unchanged_last_print_statement():
    """The 06:10 full sync must keep taking the last print of the date (golden)."""
    default = tp._quotes_sync_sql("AND UPPER(symbol) = ANY(%(syms)s)")
    assert "fetched_at DESC" in default and "fetched_at ASC" not in default
    assert "%(close_time)s" not in default and "%(close_end)s" not in default
    assert norm(default) == norm(tp._quotes_sync_sql("AND UPPER(symbol) = ANY(%(syms)s)", "",
                                                     only_missing=False))


def test_a_window_without_a_session_is_refused():
    """A window over every date would take each day's first post-close print, not one close."""
    cur = RecCursor()
    with pytest.raises(ValueError):
        tp.sync_ticker_prices_from_market_quotes(cur, ["XLF"], min_ratio=0.5, max_ratio=2.0,
                                                 close_window=(time(16, 0), time(16, 10)))
    assert cur.calls == []


# ── the classification a reader sees ────────────────────────────────────────


def test_a_symbol_with_only_after_hours_prints_is_reported_not_priced():
    """XLF's 11-06 shape: quotes that day, none inside the window -> no close, never 57.13."""
    from datetime import datetime
    et = __import__("zoneinfo").ZoneInfo("America/New_York")
    cur = RecCursor()
    cur.fetchall = lambda: [
        ("XLF", None, None, datetime(2026, 11, 6, 16, 45, 2, tzinfo=et), None, None, 57.53),
    ]
    plan = pds.plan_session_closes(cur, date(2026, 11, 6), ["XLF"])
    assert plan["no_close_print"] == ["XLF"]
    assert plan["would_write"] == [] and plan["outliers"] == []
    row = plan["rows"][0]
    assert row["close"] is None
    assert row["last_quote"].endswith("16:45:02")
    assert "16:00-16:10 ET" in plan["close_window"]


def test_the_plan_names_the_window_so_a_reader_can_see_what_it_accepted():
    cur = RecCursor()
    plan = pds.plan_session_closes(cur, date(2026, 11, 6), ["XLF"])
    assert plan["close_window"] == "16:00-16:10 ET"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
