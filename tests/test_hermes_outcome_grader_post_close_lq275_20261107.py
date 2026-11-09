"""LQ-20261107-275 (old LQ-126) — the close cache stores only post-close prices, from the data broker.

ANCHOR: HERMES_OUTCOME_GRADER_POST_CLOSE_LQ275_20261107

Hermetic: no database, no network. Recording/fake cursors capture what the grader sends; the session
calendar is the deterministic NYSE service. All symbols and prices are synthetic.

The defect. ``daily_close_cache`` took "the last quote of each calendar day" from market_quotes. The
poller runs past the bell, so that is an after-hours trade (XLK 2026-11-05: 161.75 cached vs official
162.45), and before LQ-126 it was often the 07:15 pre-market print, whose price is the previous
evening's trade: PWR's cache was one session behind (cached 11-04/05/06 = true closes of 11-03/04/05).
yfinance quotes and weekend dates (PWR "2026-11-07", a Saturday) landed in the cache too, and the grader
built its session calendar from the cached SPY dates, so a Saturday row shifted every horizon.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

NY = ZoneInfo("America/New_York")


def _sc():
    return importlib.import_module("lib.data_broker.session_close")


def _grader():
    return importlib.import_module("hermes_outcome_grader")


class RecordingCursor:
    """Records (sql, params); answers the backfill-start probe with `first_quote_date`."""

    def __init__(self, first_quote_date=None):
        self.calls: list[tuple[str, object]] = []
        self.rowcount = 0
        self._first = first_quote_date
        self._last = ""

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        self._last = str(sql)

    def fetchall(self):
        if "ORDER BY id ASC LIMIT 1" in self._last and self._first is not None:
            return [(self._first,)]
        return []


# --- the session calendar ----------------------------------------------------------------------------

def test_sessions_are_nyse_trading_days_with_their_official_close():
    ss = _sc().sessions_between(date(2026, 11, 20), date(2026, 11, 30))
    assert [s.session_date for s in ss] == [date(2026, 11, d) for d in (20, 23, 24, 25, 27, 30)]
    by = {s.session_date: s for s in ss}
    assert by[date(2026, 11, 24)].close_at == datetime(2026, 11, 24, 16, 0, tzinfo=NY)
    assert by[date(2026, 11, 27)].close_at == datetime(2026, 11, 27, 13, 0, tzinfo=NY)   # early close


def test_the_next_session_skips_weekends_and_holidays():
    by = {s.session_date: s for s in _sc().sessions_between(date(2026, 11, 20), date(2026, 11, 27))}
    assert by[date(2026, 11, 20)].next_date == date(2026, 11, 23)            # Fri -> Mon
    assert by[date(2026, 11, 25)].next_date == date(2026, 11, 27)            # Thanksgiving skipped
    assert by[date(2026, 11, 25)].next_from == datetime(2026, 11, 27, 4, 0, tzinfo=NY)
    assert by[date(2026, 11, 25)].next_until == datetime(2026, 11, 27, 13, 0, tzinfo=NY)


def test_a_saturday_is_never_a_session():
    assert _sc().sessions_between(date(2026, 11, 7), date(2026, 11, 8)) == []


# --- sources --------------------------------------------------------------------------------------------

def test_yfinance_is_never_a_close_source():
    sc = _sc()
    assert "yfinance" not in sc.SOURCES
    ss = sc.sessions_between(date(2026, 11, 2), date(2026, 11, 6))
    assert sc.session_close_params(ss)["sources"] == list(sc.SOURCES)
    with pytest.raises(ValueError):
        sc.session_close_params(ss, sources=("alpaca", "yfinance"))


# --- the SELECT: post-close only --------------------------------------------------------------------------

def _cte(sql: str, name: str) -> str:
    body = sql.split(f"{name} AS (", 1)[1]
    return body.split("\n), ", 1)[0] if "\n), " in body else body.split("\n)\nSELECT", 1)[0]


def test_the_official_close_is_prev_close_on_the_next_session_after_the_bell():
    off = _cte(_sc().session_close_sql(), "official")
    assert "q.prev_close AS close_price" in off
    assert "q.ny_date = s.next_date" in off
    assert "q.quote_at > s.close_at" in off
    assert "q.quote_at >= s.next_from AND q.quote_at < s.next_until" in off
    assert re.search(r"ORDER BY q\.symbol, s\.session_date, q\.quote_at ASC, q\.quote_id ASC$", off.strip())


def test_the_provisional_close_is_the_first_print_inside_the_grace_window_after_the_bell():
    pc = _cte(_sc().session_close_sql(), "post_close")
    assert "q.price AS close_price" in pc
    assert "q.quote_at >= s.close_at AND q.quote_at < s.close_at + make_interval(secs => %(grace)s)" in pc
    assert "q.quote_at ASC" in pc and "DESC" not in pc
    assert _sc().session_close_params(_sc().sessions_between(date(2026, 11, 6), date(2026, 11, 6)))["grace"] == 300


def test_no_price_reaches_the_output_except_through_a_post_close_check():
    sql = _sc().session_close_sql()
    # the two CTEs are the only places a price becomes close_price, and each carries a close_at bound
    assert sql.count("AS close_price") == 2 + 1          # official, post_close, and the final COALESCE
    for name in ("official", "post_close"):
        assert "s.close_at" in _cte(sql, name)
    assert "fetched_at DESC" not in sql                   # the "last quote of the day" rule is gone


def test_every_named_param_is_supplied_with_and_without_a_symbol_filter():
    sc = _sc()
    ss = sc.sessions_between(date(2026, 11, 2), date(2026, 11, 6))
    for with_symbols, symbols in ((False, None), (True, ["zzza", "ZZZB "])):
        sql = sc.session_close_sql(with_symbols=with_symbols)
        params = sc.session_close_params(ss, symbols=symbols)
        assert set(re.findall(r"%\((\w+)\)s", sql)) == set(params), with_symbols
        assert "%s" not in sql
    assert sc.session_close_params(ss, symbols=["zzza", "ZZZB "])["symbols"] == ["ZZZA", "ZZZB"]
    p = sc.session_close_params(ss)
    assert p["lo"] == ss[0].close_at and p["hi"] == ss[-1].next_until


# --- the grader writes from the projection --------------------------------------------------------------

def test_refresh_inserts_the_projection_over_calendar_sessions_only():
    g, sc = _grader(), _sc()
    cur = RecordingCursor()
    g.refresh_close_cache(cur, {"close_cache_refresh_days": 4}, today=date(2026, 11, 9))   # a Monday
    sql, params = cur.calls[0]
    assert sc.session_close_sql() in sql
    assert params["session_date"] == [date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9)]
    assert params["src_prefix"] == "market_quotes:"
    assert set(re.findall(r"%\((\w+)\)s", sql)) == set(params)


def test_a_provisional_close_never_overwrites_an_official_one():
    g = _grader()
    cur = RecordingCursor()
    g.refresh_close_cache(cur, {"close_cache_refresh_days": 4}, today=date(2026, 11, 9))
    sql, params = cur.calls[0]
    tail = sql.split("ON CONFLICT", 1)[1]
    assert "WHERE daily_close_cache.source IS DISTINCT FROM %(src_official)s" in tail
    assert "OR EXCLUDED.source = %(src_official)s" in tail
    assert params["src_official"] == g.SRC_OFFICIAL == "market_quotes:next_session_prev_close"
    assert g.SRC_POST_CLOSE == "market_quotes:post_close_quote"


def test_backfill_starts_at_the_first_stored_quote_and_writes_in_chunks():
    g = _grader()
    cur = RecordingCursor(first_quote_date=date(2026, 8, 10))
    g.refresh_close_cache(cur, {}, backfill=True, today=date(2026, 11, 6))
    assert "ORDER BY id ASC LIMIT 1" in cur.calls[0][0] and cur.calls[0][1] is None
    inserts = [p for s, p in cur.calls if "unnest(" in s]
    days = [d for p in inserts for d in p["session_date"]]
    assert days[0] == date(2026, 8, 10) and days[-1] == date(2026, 11, 6)
    assert len(days) == len(set(days)) == 64                      # 2026-08-10..11-06: 64 sessions
    assert all(len(p["session_date"]) <= g.BACKFILL_CHUNK_SESSIONS for p in inserts)
    assert len(inserts) == -(-64 // g.BACKFILL_CHUNK_SESSIONS)


def test_a_hostile_refresh_window_raises_before_any_sql():
    cur = RecordingCursor()
    with pytest.raises(ValueError):
        _grader().refresh_close_cache(cur, {"close_cache_refresh_days": "4; DROP TABLE x"})
    assert cur.calls == []


# --- the grader's calendar ignores non-session cache rows ----------------------------------------------

class GradeCursor:
    """Answers the three reads grade() makes; records UPDATEs."""

    def __init__(self, spy_dates, ledger, px):
        self.spy_dates, self.ledger, self.px = spy_dates, ledger, px
        self.updates: list[tuple] = []
        self._rows: list = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        if s.startswith("SELECT price_date FROM daily_close_cache"):
            self._rows = [(d,) for d in self.spy_dates]
        elif s.startswith("SELECT id, subject_type"):
            self._rows = list(self.ledger)
        elif s.startswith("SELECT symbol, price_date, close_price FROM daily_close_cache"):
            self._rows = [(k[0], k[1], v) for k, v in self.px.items()]
        elif s.startswith("UPDATE"):
            self.updates.append((s, params))
            self._rows = []
        else:
            raise AssertionError(f"unexpected SQL: {s[:80]}")

    def fetchall(self):
        return self._rows


def _trading_days(start, n):
    svc = importlib.import_module("lib.cio_market_session").get_session_service()
    out, d = [], start
    while len(out) < n:
        if svc.is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def test_sessions_drop_a_weekend_cache_row():
    days = _trading_days(date(2026, 11, 2), 5) + [date(2026, 11, 7)]
    cur = GradeCursor(sorted(days), [], {})
    assert date(2026, 11, 7) not in _grader()._sessions(cur, "SPY")


def test_a_saturday_row_does_not_shift_the_20_session_horizon():
    g = _grader()
    sess = _trading_days(date(2026, 9, 1), 30)
    saturday = next(d for d in (sess[3] + timedelta(days=k) for k in range(7)) if d.weekday() == 5)
    spy_dates = sorted(sess + [saturday])
    px = {("SPY", d): 100.0 for d in sess}
    px[("SPY", saturday)] = 100.0
    px.update({("ZZZQ", d): 50.0 for d in sess})
    px[("ZZZQ", sess[20])] = 55.0          # +10% exactly 20 sessions after the base session
    px[("ZZZQ", saturday)] = 50.0
    ledger = [(1, "external_rec", "ZZZQ", sess[0], "long", "pending", None)]
    cfg = {"benchmark": "SPY", "horizons": {"short_sessions": 5, "long_sessions": 20},
           "verdict": {"hit_pct": 2.0, "miss_pct": -2.0}, "max_rows_per_run": 10}
    cur = GradeCursor(spy_dates, ledger, px)
    out = g.grade(cur, cfg)
    assert out["sessions"] == 30
    final = [p for s, p in cur.updates if "verdict=%s" in s]
    assert final and final[0][2] == 55.0 and final[0][5] == "hit", final


@pytest.fixture
def archive_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADE_AI_CI", "1")
    return tmp_path


def _archive_lines(root: Path) -> list[dict]:
    path = root / "data" / "cio" / "hermes_outcome_verdict_archive.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _research_cfg():
    return {"benchmark": "SPY", "horizons": {"short_sessions": 5, "long_sessions": 20},
            "verdict": {"hit_pct": 2.0, "miss_pct": -2.0}, "max_rows_per_run": 10,
            "research_action_window_days": 14}


def _flat_book(sess, sym="ZZZQ"):
    px = {("SPY", d): 100.0 for d in sess}
    px.update({(sym, d): 50.0 for d in sess})
    return px


def test_a_research_row_inside_the_20_session_horizon_stays_pending(archive_root):
    """Engagement is not a verdict. Before 20 sessions the row is not graded."""
    g = _grader()
    sess = _trading_days(date(2026, 9, 1), 30)
    px = _flat_book(sess)
    ledger = [(7, "research_row", "ZZZQ", sess[20], "long", "pending", None)]
    cur = GradeCursor(sess, ledger, px)
    out = g.grade(cur, _research_cfg())
    assert out["still_pending"] == 1
    assert out["verdicts_archived"] == 0
    assert [p for s, p in cur.updates if "verdict=%s" in s] == []
    assert any("verdict='pending'" in s for s, _p in cur.updates)
    assert _archive_lines(archive_root) == []


def test_a_research_row_hit_is_the_20_session_excess_not_a_directive(archive_root):
    g = _grader()
    sess = _trading_days(date(2026, 9, 1), 30)
    px = _flat_book(sess)
    px[("ZZZQ", sess[20])] = 55.0
    ledger = [(7, "research_row", "ZZZQ", sess[0], "long", "pending", None)]
    cur = GradeCursor(sess, ledger, px)
    g.grade(cur, _research_cfg())
    final = [p for s, p in cur.updates if "verdict=%s" in s]
    assert final and final[0][5] == "hit" and final[0][4] == 10.0


def test_a_research_row_miss_is_the_20_session_excess(archive_root):
    g = _grader()
    sess = _trading_days(date(2026, 9, 1), 30)
    px = _flat_book(sess)
    px[("ZZZQ", sess[20])] = 40.0
    ledger = [(7, "research_row", "ZZZQ", sess[0], "long", "pending", None)]
    cur = GradeCursor(sess, ledger, px)
    g.grade(cur, _research_cfg())
    final = [p for s, p in cur.updates if "verdict=%s" in s]
    assert final and final[0][5] == "miss"


def test_a_research_row_inside_the_band_is_neutral_once_the_horizon_arrives(archive_root):
    g = _grader()
    sess = _trading_days(date(2026, 9, 1), 30)
    px = _flat_book(sess)
    px[("ZZZQ", sess[20])] = 50.5
    ledger = [(7, "research_row", "ZZZQ", sess[0], "long", "pending", None)]
    cur = GradeCursor(sess, ledger, px)
    g.grade(cur, _research_cfg())
    final = [p for s, p in cur.updates if "verdict=%s" in s]
    assert final and final[0][5] == "neutral"


def test_a_research_hit_is_archived_before_the_rewrite(archive_root):
    """The prior verdict is on disk even when the UPDATE then fails."""
    g = _grader()
    sess = _trading_days(date(2026, 9, 1), 30)
    px = _flat_book(sess)
    px[("ZZZQ", sess[20])] = 40.0
    prior_at = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
    ledger = [(7, "research_row", "ZZZQ", sess[0], "long", "hit", prior_at)]

    class Stop(GradeCursor):
        def execute(self, sql, params=None):
            compact = " ".join(str(sql).split())
            if compact.startswith("UPDATE") and "verdict=%s" in compact:
                raise RuntimeError("update refused")
            super().execute(sql, params)

    with pytest.raises(RuntimeError, match="update refused"):
        g.grade(Stop(sess, ledger, px), _research_cfg())
    lines = _archive_lines(archive_root)
    assert len(lines) == 1
    assert lines[0]["ledger_id"] == 7
    assert lines[0]["subject_type"] == "research_row"
    assert lines[0]["prior_verdict"] == "hit"
    assert lines[0]["prior_graded_at"] == "2026-10-01T15:00:00Z"
    assert lines[0]["new_verdict"] == "miss"
    assert lines[0]["reason"] == "price_verdict"
    assert lines[0]["schema"] == "HermesOutcomeVerdictArchive@v1"
    assert "symbol" not in lines[0]


def test_a_premature_research_hit_is_archived_before_it_returns_to_pending(archive_root):
    g = _grader()
    sess = _trading_days(date(2026, 9, 1), 30)
    px = _flat_book(sess)
    prior_at = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    ledger = [(7, "research_row", "ZZZQ", sess[20], "long", "hit", prior_at)]
    cur = GradeCursor(sess, ledger, px)
    out = g.grade(cur, _research_cfg())
    assert out["still_pending"] == 1 and out["verdicts_archived"] == 1
    lines = _archive_lines(archive_root)
    assert len(lines) == 1
    assert lines[0]["prior_verdict"] == "hit"
    assert lines[0]["prior_graded_at"] == "2026-10-02T12:00:00Z"
    assert lines[0]["new_verdict"] == "pending"
    assert lines[0]["new_graded_at"] is None
    assert lines[0]["reason"] == "reset_pending"
    assert any("verdict='pending'" in sql for sql, _params in cur.updates)


def test_a_non_research_grade_does_not_archive(archive_root):
    g = _grader()
    sess = _trading_days(date(2026, 9, 1), 30)
    px = _flat_book(sess)
    px[("ZZZQ", sess[20])] = 55.0
    ledger = [(1, "external_rec", "ZZZQ", sess[0], "long", "pending", None)]
    cur = GradeCursor(sess, ledger, px)
    out = g.grade(cur, _research_cfg())
    assert out["verdicts_archived"] == 0
    assert _archive_lines(archive_root) == []
    final = [params for sql, params in cur.updates if "verdict=%s" in sql]
    assert final and final[0][5] == "hit"


def test_the_archive_appends_and_skips_a_same_state_write(archive_root):
    g = _grader()
    stamp = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
    assert g.remember_research_verdict(
        ledger_id=7, prior_verdict="hit", prior_graded_at=stamp,
        new_verdict="hit", new_graded_at=stamp, reason="price_verdict",
    ) is False
    assert _archive_lines(archive_root) == []
    assert g.remember_research_verdict(
        ledger_id=7, prior_verdict="hit", prior_graded_at=stamp,
        new_verdict="miss", new_graded_at=stamp, reason="price_verdict",
    ) is True
    assert g.remember_research_verdict(
        ledger_id=9, prior_verdict="neutral", prior_graded_at=stamp,
        new_verdict="pending", new_graded_at=None, reason="reset_pending",
    ) is True
    lines = _archive_lines(archive_root)
    assert [row["ledger_id"] for row in lines] == [7, 9]
    assert lines[0]["prior_verdict"] == "hit" and lines[0]["new_verdict"] == "miss"
    text = (archive_root / "data" / "cio" / "hermes_outcome_verdict_archive.jsonl").read_text(encoding="utf-8")
    assert text.count("\n") == 2


def test_a_test_process_refuses_the_live_archive(monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.delenv("TRADEAI_PERSISTENT_STATE_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="live hermes verdict archive"):
        _grader().verdict_archive_path()


def test_recording_a_directive_does_not_write_a_hit(monkeypatch):
    g = _grader()
    seen: list[str] = []

    class Cur:
        rowcount = 1

        def execute(self, sql, params=None):
            seen.append(" ".join(str(sql).split()))

    writer = importlib.import_module("lib.writers.hermes_research_writer")

    def _link(cur, **kwargs):
        seen.append("link")
        return type("R", (), {"rows_written": 0})()

    monkeypatch.setattr(writer, "link_from_join", _link)
    out = g.grade_research_actions(Cur(), _research_cfg())
    assert out["research_actioned"] == 1
    updates = [s for s in seen if "UPDATE hermes_outcome_ledger" in s]
    assert len(updates) == 1 and "actioned = j.act" in updates[0]
    assert "verdict" not in updates[0]
    assert "graded_at" not in updates[0]


# --- the read model ---------------------------------------------------------------------------------------

def test_get_session_closes_returns_rows_with_their_method_and_never_fetches():
    sc = _sc()
    seen = {}

    def db_query(sql, params, fetch=None):
        seen["sql"], seen["params"] = sql, params
        return [{"symbol": "ZZZA", "session_date": date(2026, 11, 5), "close_price": 12.5,
                 "method": sc.METHOD_OFFICIAL, "quote_at": datetime(2026, 11, 6, 7, 15, tzinfo=NY)}]

    out = sc.get_session_closes(db_query, date(2026, 11, 5), date(2026, 11, 5), symbols=["zzza"])
    assert out["ok"] and out["provider_calls"] == 0 and out["n"] == 1
    assert out["closes"][0] == {"symbol": "ZZZA", "session_date": "2026-11-05", "close": 12.5,
                                "method": "next_session_prev_close", "quote_at": "2026-11-06T07:15:00-05:00"}
    assert seen["params"]["symbols"] == ["ZZZA"] and "ANY(%(symbols)s)" in seen["sql"]
    assert sc.get_session_closes(db_query, date(2026, 11, 7), date(2026, 11, 8))["closes"] == []


def test_the_projection_is_in_the_data_broker_catalog():
    cat = importlib.import_module("lib.data_broker.catalog")
    entries = [e for e in cat.PROJECTIONS if e.get("id") == "session_close"]
    assert entries, "session_close missing from lib.data_broker.catalog"
    e = entries[0]
    assert e["module"] == "lib.data_broker.session_close" and e["read_only"] and e["provider_calls"] == 0
    mod = importlib.import_module(e["module"])
    assert all(callable(getattr(mod, ep)) for ep in e["entrypoints"])
