"""LQ-20261107-1264 (+ AMENDMENT 1): the off-hours universe, the Friday window, and the words a card uses.

Three things the operator measured on 2026-11-08:
  * V, MU, SCHD, AXTI, DXCM had ZERO rows in market_quotes_extended — the lane only ever fetched a fixed 23-name list,
    so a held, stopped-out or watched name was never requested at all;
  * Friday's own 16:00-20:00 after-hours was never fetched from Schwab (the window stopped at 09:30);
  * the cards printed "now —" and a bare "stale" instead of naming the session, the time, and when trading resumes.

Synthetic fixtures only (public repo).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib import market_risk_book_join as bj  # noqa: E402
from scripts.lib import offhours_quotes as oq  # noqa: E402
from scripts.lib import session_now as sn  # noqa: E402
from scripts.lib.data_broker import market_quote as mq  # noqa: E402

ET = ZoneInfo("America/New_York")
CFG = oq.load_config()


# ── the universe: config-declared SQL sources, never a hard-coded list ────────────────────────────────────────────

def _cfg(*sources):
    return {"universe": {"sources": list(sources)}}


def test_a_sql_source_joins_the_universe_and_its_count_is_on_the_receipt():
    seen = []

    def db_query(sql):
        seen.append(sql)
        return [("V",), ("MU",), ("SCHD",)]

    merged, prov = oq.resolve_universe(
        _cfg({"name": "positions_current", "sql": "SELECT 1"}, {"name": "stopped_out_30d", "sql": "SELECT 2"}),
        db_query=db_query,
    )
    assert merged == ["V", "MU", "SCHD"]
    assert prov["counts"] == {"sql:positions_current": {"kept": 3}, "sql:stopped_out_30d": {"kept": 3}}
    assert len(seen) == 2 and prov["missing_refs"] == []


def test_the_configured_queries_are_the_ones_that_run():
    """The three sources the amendment asks for are DECLARED IN CONFIG, not spelled in code."""
    sqls = " ".join(str(s.get("sql") or "") for s in CFG["universe"]["sources"])
    names = {str(s.get("name") or "") for s in CFG["universe"]["sources"]}
    assert {"positions_current", "stopped_out_30d", "watchlist_active"} <= names
    assert "positions_current" in sqls and "trade_closed" in sqls and "watchlist_items" in sqls


def test_a_failing_query_is_named_and_the_rest_of_the_universe_survives():
    def db_query(sql):
        if "fail" in sql:
            raise RuntimeError("permission denied")
        return [("V",)]

    merged, prov = oq.resolve_universe(
        _cfg({"name": "broken", "sql": "SELECT fail"}, {"name": "ok", "sql": "SELECT 1"}), db_query=db_query)
    assert merged == ["V"]
    assert any("sql:broken" in m and "RuntimeError" in m for m in prov["missing_refs"])


def test_a_sql_source_with_no_reader_is_named_not_skipped_silently():
    merged, prov = oq.resolve_universe(_cfg({"name": "positions_current", "sql": "SELECT 1"}), db_query=None)
    assert merged == []
    assert any("no database reader wired" in m for m in prov["missing_refs"])


def test_a_limit_is_a_named_bound_not_a_silent_filter():
    merged, prov = oq.resolve_universe(
        _cfg({"name": "watchlist_active", "sql": "SELECT 1", "limit": 2}),
        db_query=lambda _s: [("A",), ("B",), ("C",)])
    assert merged == ["A", "B"]
    assert prov["counts"]["sql:watchlist_active"] == {"kept": 2, "truncated_from": 3}


# ── the window: Friday's own after-hours ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("when,inside", [
    ("2026-11-06 17:00", True),    # Friday after-hours — the amendment's gap
    ("2026-11-06 19:59", True),
    ("2026-11-06 21:00", False),   # Friday night is outside; the lane's window still ends Friday evening
    ("2026-11-07 12:00", False),   # Saturday
    ("2026-11-08 20:30", True),    # Sunday overnight open is inside the main span (it starts at 18:00)
    ("2026-11-04 03:00", True),    # a weekday overnight
])
def test_the_window_covers_friday_afterhours_and_the_sunday_open(when, inside):
    now = datetime.fromisoformat(when).replace(tzinfo=ET)
    ok, why = oq.schwab_window(now, CFG)
    assert ok is inside, why


def test_the_window_comes_from_config_so_the_operator_can_widen_it_without_a_deploy():
    cfg = {"schwab": {"window": {"start_day": "sun", "start": "18:00", "end_day": "fri", "end": "09:30",
                                 "extra_segments": [{"day": "sat", "start": "10:00", "end": "12:00"}]}}}
    sat = datetime(2026, 11, 7, 11, 0, tzinfo=ET)
    assert oq.schwab_window(sat, cfg)[0] is True
    assert oq.schwab_window(sat + timedelta(hours=3), cfg)[0] is False


# ── the words ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_next_futures_open_is_the_next_sunday_six_pm_et():
    fri = datetime(2026, 11, 6, 15, 0, tzinfo=ET)
    assert sn.next_futures_open(fri).isoformat() == "2026-11-08T18:00:00-05:00"
    before = datetime(2026, 11, 8, 17, 59, tzinfo=ET)
    assert sn.next_futures_open(before).isoformat() == "2026-11-08T18:00:00-05:00"
    after = datetime(2026, 11, 8, 18, 1, tzinfo=ET)
    assert sn.next_futures_open(after).isoformat() == "2026-11-15T18:00:00-05:00"


def test_the_two_sentences_the_operator_asked_for():
    fri = datetime(2026, 11, 6, 15, 0, tzinfo=ET)
    assert sn.next_session_text(fri, "futures") == "futures open Sun 6:00 PM ET"
    assert sn.next_session_text(fri, "overnight") == "next trading: overnight session opens Sun 8:00 PM ET"


def test_mark_label_names_the_session_time_price_and_change():
    at = datetime(2026, 11, 6, 19, 58, tzinfo=ET)
    assert sn.mark_label("afterhours", at, 424.10, 0.3) == "after-hours Fri 7:58 PM $424.10 (+0.3%)"


def test_a_level_only_mark_never_shows_a_change():
    at = datetime(2026, 11, 6, 19, 58, tzinfo=ET)
    assert sn.mark_label("overnight", at, 6810.25, None) == "overnight Fri 7:58 PM $6,810.25 level only"


def test_an_unknown_session_is_its_raw_value_and_never_invented():
    assert sn.mark_label("weird_session", None, None, None) == "weird_session level only"


# ── the Home block: a stale print before Sunday's open says when it refreshes ─────────────────────────────────────

class _Cur:
    def __init__(self, rows):
        self._rows, self._out = rows, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self._out = self._rows

    def fetchall(self):
        return self._out


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cur(self._rows)

    def rollback(self):
        pass


POLICY = {"home_review": {"overnight_markets": {"enabled": True, "stale_after_hours": 12, "max_items": 11}}}


def test_a_stale_overnight_item_names_the_futures_open_instead_of_a_bare_stale():
    now = datetime(2026, 11, 7, 12, 0, tzinfo=ET)  # Saturday: nothing is open
    bar_end = datetime(2026, 11, 6, 19, 45, tzinfo=ET)
    conn = _Conn([("/ES", "afterhours", None, 6810.25, 0.45, "schwab_quote_close_price_settle_dated", None, bar_end)])
    out = bj.overnight_markets(conn, now, POLICY)
    item = out["items"][0]
    assert item["stale"] is True
    assert item["stale_reason"] == "futures open Sun 6:00 PM ET"
    assert out["next_session"]["text"] == "futures open Sun 6:00 PM ET"
    assert item["mark_label"].startswith("after-hours Fri 7:45 PM $6,810.25")


def test_a_fresh_item_carries_no_reason():
    now = datetime(2026, 11, 6, 19, 50, tzinfo=ET)
    conn = _Conn([("/ES", "afterhours", None, 6810.25, 0.45, "basis", None, now - timedelta(minutes=5))])
    item = bj.overnight_markets(conn, now, POLICY)["items"][0]
    assert item["stale"] is False and item["stale_reason"] is None


# ── the extended store: a Friday after-hours print outranks the regular close ─────────────────────────────────────

def test_the_extended_mark_carries_its_session_and_a_ready_label():
    bar_end = datetime(2026, 11, 6, 19, 58, tzinfo=ET)
    out = mq._extended_batch(lambda sql, params, fetch: [("V", "afterhours", 424.10, 0.3, "basis", bar_end, "schwab")],
                             ["V"], 96 * 3600.0, now=datetime(2026, 11, 7, 12, 0, tzinfo=ET))
    assert out["V"]["label"] == "after-hours Fri 7:58 PM $424.10 (+0.3%)"
    assert out["V"]["source"] == "data_broker.market_quotes_extended:schwab:afterhours"


def test_a_broken_extended_read_is_stated_as_unknown_not_as_none_stored():
    """A failed read must not be indistinguishable from "nothing printed after-hours"."""
    def boom(*a, **k):
        raise RuntimeError("relation does not exist")

    assert mq._extended_batch(boom, ["V"], 3600.0, now=datetime(2026, 11, 7, tzinfo=timezone.utc)) == {"__unknown__": True}


def test_the_failed_extended_read_reaches_the_marks_the_caller_keeps(monkeypatch):
    class _LQ:
        @staticmethod
        def get_latest_quotes(db_query, symbols, max_age_seconds):
            return {"fresh": symbols, "symbols": {s: {"price": 420.0, "chg_pct": -0.5,
                                                      "as_of": "2026-11-06T21:00:00+00:00", "provider": "alpaca"}
                                                  for s in symbols}}

    monkeypatch.setattr("lib.data_broker.latest_quote.get_latest_quotes", _LQ.get_latest_quotes)

    def boom(*a, **k):
        raise RuntimeError("relation does not exist")

    out = mq.get_price_batch(boom, ["V"], max_age_hours=96, skip_live=True)
    assert out["V"]["extended_unknown"] is True and out["V"]["price"] == 420.0


def test_the_newer_of_the_two_stores_wins(monkeypatch):
    """The regular close is Friday 16:00; the after-hours print is Friday 19:58. The card must show the second."""
    class _LQ:
        @staticmethod
        def get_latest_quotes(db_query, symbols, max_age_seconds):
            return {"fresh": symbols, "symbols": {s: {"price": 420.0, "chg_pct": -0.5, "as_of": "2026-11-06T21:00:00+00:00",
                                                      "provider": "alpaca"} for s in symbols}}

    monkeypatch.setattr("lib.data_broker.latest_quote.get_latest_quotes", _LQ.get_latest_quotes)
    ext_end = datetime(2026, 11, 6, 19, 58, tzinfo=ET)

    def db_query(sql, params, fetch="all"):
        return [("V", "afterhours", 424.10, 0.3, "basis", ext_end, "schwab")]

    out = mq.get_price_batch(db_query, ["V"], max_age_hours=96, skip_live=True)
    assert out["V"]["price"] == 424.10
    assert out["V"]["session"] == "afterhours"
    assert out["V"]["label"] == "after-hours Fri 7:58 PM $424.10 (+0.3%)"


def test_extended_batch_dict_rows_lq1291():
    """Production _db_query returns dict rows; unpacking one gave its keys -> float('price') 500."""
    from datetime import datetime, timezone
    bar_end = datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc)
    row = {"symbol": "V", "session": "afterhours", "price": 424.10, "change_pct": 0.3,
           "reference_basis": "basis", "bar_end": bar_end, "feed": "schwab"}
    bad = dict(row, symbol="W", price="not-a-number")
    out = mq._extended_batch(lambda sql, params, fetch: [row, bad], ["V", "W"], 96 * 3600.0,
                             now=datetime(2026, 11, 7, 2, 0, tzinfo=timezone.utc))
    assert out["V"]["price"] == 424.10 and out["V"]["chg_pct"] == 0.3
    assert "W" not in out
