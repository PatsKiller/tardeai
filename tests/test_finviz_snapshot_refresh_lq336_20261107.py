"""LQ-20261107-336 (WP0a): the Finviz snapshot refresh that backfills the 11-06 close.

``ticker_snapshot_daily`` had no row after 2026-11-03: its only writer is stage 11 of
``portfolio_orchestrator.py`` and stage 1 crashed on 11-04..06 (``asset_type`` None → ``.upper()``,
FU-007). ``fundamental_data``'s only writer is the Monday ``--fundamentals`` lane. This lane refreshes
both for one session close over holdings + active watchlist + recent screener members.

What is pinned here:

* the row carries the **close** session, not the day it ran (a Saturday run dates the row Friday);
* the universe is holdings ∪ active watchlist ∪ recent screener members, de-duplicated, and a screen
  that last ran outside the window contributes no names — it is *reported*, never silently dropped;
* a symbol the run did not actually refresh is never written as this close (``not_refreshed``);
* ``produced_count`` is a READ-BACK of the table, because ``save_ticker_snapshot_daily`` swallows its
  own failure and returns None — a sent count is not evidence;
* ``skipped_reasons`` partitions ``attempted`` (produced + skipped == attempted);
* a dry run writes no receipt and makes no fetch.

Hermetic: fake connections, fake enrichment cache, stub writer/ingest, ``TRADEAI_STATE_ROOT`` in tmp.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_snapshot_refresh as R  # noqa: E402
from lib import lane_last_receipt as LR  # noqa: E402

LANE = "finviz-snapshot-refresh"


class FakeCursor:
    def __init__(self, answers):
        self.answers = answers
        self.last = None
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.last = (sql, params)

    def fetchone(self):
        return self.answers.pop(0) if self.answers else (0,)

    def fetchall(self):
        return self.answers.pop(0) if self.answers else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.cursor_obj = FakeCursor(self.answers)
        self.rolled_back = 0

    def cursor(self):
        return self.cursor_obj

    def rollback(self):
        self.rolled_back += 1


@pytest.fixture
def state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return tmp_path


def test_a_saturday_run_dates_the_row_friday(monkeypatch):
    """The close, not the run: a weekend row dated Saturday would claim a quote that never traded."""
    import lib.cio_market_calendar as cal

    monkeypatch.setattr(cal, "is_us_trading_day", lambda d: date.fromisoformat(str(d)).weekday() < 5)
    assert R.last_session_close(date(2026, 11, 7)) == "2026-11-06"   # Saturday → Friday
    assert R.last_session_close(date(2026, 11, 6)) == "2026-11-06"   # a session is its own close
    assert R.last_session_close(date(2026, 11, 9)) == "2026-11-09"   # Monday


def test_last_session_close_refuses_to_guess(monkeypatch):
    import lib.cio_market_calendar as cal

    monkeypatch.setattr(cal, "is_us_trading_day", lambda d: False)
    with pytest.raises(RuntimeError, match="refusing to guess"):
        R.last_session_close(date(2026, 11, 7))


def test_holdings_symbols_skip_cash_and_loans(tmp_path):
    p = tmp_path / "data" / "portfolios" / "state"
    p.mkdir(parents=True)
    (p / "holdings.json").write_text(json.dumps({"holdings": [
        {"symbol": "noc"},
        {"symbol": "cash", "is_cash": True},
        {"symbol": "LOANX", "is_loan": True},
        {"symbol": ""},
        {"symbol": "schd"},
    ]}))
    assert R.holdings_symbols(tmp_path) == ["NOC", "SCHD"]


def test_universe_is_a_deduped_union_in_source_order(tmp_path, monkeypatch):
    (tmp_path / "data" / "portfolios" / "state").mkdir(parents=True)
    (tmp_path / "data" / "portfolios" / "state" / "holdings.json").write_text(
        json.dumps({"holdings": [{"symbol": "AAA"}, {"symbol": "BBB"}]}))
    monkeypatch.setattr(R, "watchlist_symbols", lambda conn, cap=0: ["BBB", "CCC"])
    monkeypatch.setattr(R, "screener_members", lambda conn, max_age_days=0: (["CCC", "DDD"], {"stale_screens": 3}))
    uni = R.build_universe(tmp_path, FakeConn(), extra=["ddd", "EEE"])
    assert uni["symbols"] == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    assert uni["sources"] == {"holdings": 2, "watchlist": 2, "screener_members": 2, "explicit": 2,
                              "overlap_deduped": 3}
    assert uni["screens"] == {"stale_screens": 3}


def test_a_screen_that_did_not_run_recently_contributes_names_and_a_count():
    """Members come from the windowed join; the stale screens are reported, not silently widened in."""
    conn = FakeConn(answers=[[("AAA",), ("BBB",)], (41,)])
    members, screens = R.screener_members(conn, max_age_days=14)
    assert members == ["AAA", "BBB"] and screens == {"stale_screens": 41, "max_age_days": 14}
    sql, params = conn.cursor_obj.last
    assert "finviz_screeners" in sql and params == (14,)


def test_a_record_the_run_did_not_refresh_is_not_dated_as_this_close():
    started = datetime(2026, 11, 7, 18, 0, 0)
    assert R._fresh_after({"cached_at": started.isoformat()}, started) is True
    assert R._fresh_after({"cached_at": (started - timedelta(days=2)).isoformat()}, started) is False
    assert R._fresh_after({}, started) is False
    assert R._fresh_after({"cached_at": "not-a-time"}, started) is False


def test_lane_output_partitions_attempted():
    out = R.lane_output(produced=90, attempted=100, skipped={"not_refreshed": 6, "rejected_non_ticker": 4},
                        snapshot_date="2026-11-06")
    assert out["produced_count"] + sum(out["skipped_reasons"].values()) == out["attempted_count"] == 100
    assert out["empty_reason"] is None
    empty = R.lane_output(produced=0, attempted=3, skipped={}, snapshot_date="2026-11-06")
    assert empty["empty_reason"] == "no_refreshed_records"


def test_apply_counts_the_table_not_what_it_sent(tmp_path, monkeypatch):
    """``save_ticker_snapshot_daily`` swallows its failure — so a write that lands nothing must read as zero."""
    started = datetime.now()
    rec = {"cached_at": started.isoformat(), "price": 10.0}
    monkeypatch.setattr(R, "_connect", lambda readonly: FakeConn())
    monkeypatch.setattr(R, "build_universe", lambda *a, **k: {
        "symbols": ["AAA", "BBB"], "sources": {}, "screens": {}})
    fi = types.ModuleType("finviz_enrichment")
    fi._split_equities = lambda syms: (list(syms), [])
    fi.enrich_tickers = lambda syms, **k: {"AAA": rec, "BBB": {"symbol": "BBB", "rejected_non_ticker": "x"}}
    monkeypatch.setitem(sys.modules, "finviz_enrichment", fi)
    da = types.ModuleType("db_adapter")
    da.save_ticker_snapshot_daily = lambda date, rows: None      # the real one's contract: no return, even on failure
    monkeypatch.setitem(sys.modules, "db_adapter", da)
    em = types.ModuleType("external_market_data_ingest")
    em.ingest_finviz_fundamentals = lambda syms, limit=0: {"rows": 9, "fetched": 1}
    monkeypatch.setitem(sys.modules, "external_market_data_ingest", em)
    monkeypatch.setattr(R, "count_snapshot_rows", lambda conn, d, syms: 0)

    out = R.apply(tmp_path, snapshot_date="2026-11-06", cap=10, screen_max_age_days=14, extra=None,
                  force_refresh=True, fundamentals_limit=200)
    assert out["snapshot_rows_verified"] == 0            # sent 1 record, verified 0
    assert out["skipped"] == {"not_refreshed": 1, "write_unverified": 1}
    assert out["symbols"] == 2


def test_apply_writes_the_verified_rows_and_reports_the_rest(tmp_path, monkeypatch):
    started = datetime.now()
    fresh = {"cached_at": started.isoformat(), "price": 10.0}
    monkeypatch.setattr(R, "_connect", lambda readonly: FakeConn())
    monkeypatch.setattr(R, "build_universe", lambda *a, **k: {
        "symbols": ["AAA", "BBB", "CCC"], "sources": {}, "screens": {}})
    fi = types.ModuleType("finviz_enrichment")
    fi._split_equities = lambda syms: (list(syms), [{"symbol": "12507E201", "reason": "cusip"}])
    fi.enrich_tickers = lambda syms, **k: {"AAA": fresh, "BBB": fresh, "CCC": {"cached_at": "2026-08-01T00:00:00"}}
    monkeypatch.setitem(sys.modules, "finviz_enrichment", fi)
    written = {}

    def _save(date, rows):
        written.update(rows)
        return None

    da = types.ModuleType("db_adapter")
    da.save_ticker_snapshot_daily = _save
    monkeypatch.setitem(sys.modules, "db_adapter", da)
    em = types.ModuleType("external_market_data_ingest")
    em.ingest_finviz_fundamentals = lambda syms, limit=0: {"rows": 6, "fetched": len(syms)}
    monkeypatch.setitem(sys.modules, "external_market_data_ingest", em)
    monkeypatch.setattr(R, "count_snapshot_rows", lambda conn, d, syms: len(written))

    out = R.apply(tmp_path, snapshot_date="2026-11-06", cap=10, screen_max_age_days=14, extra=None,
                  force_refresh=True, fundamentals_limit=200)
    assert set(written) == {"AAA", "BBB"}          # CCC never refreshed → never dated as this close
    assert out["snapshot_rows_verified"] == 2
    assert out["skipped"] == {"not_refreshed": 1, "rejected_non_ticker": 1}
    assert out["fundamentals_rows"] == 6


def test_a_dry_run_writes_no_receipt_and_plans_the_spend(tmp_path, monkeypatch, state_root, capsys):
    monkeypatch.setattr(R, "plan", lambda *a, **k: {
        "snapshot_date": "2026-11-06", "universe": ["AAA", "BBB"], "sources": {}, "screens": {},
        "equities": 2, "rejected_non_ticker": [], "cached_now": 0, "to_fetch": 2, "to_fetch_first": ["AAA"],
        "views": [111, 121], "finviz_export_requests": 2, "would_write_snapshot_rows": 2,
        "would_write_fundamental_symbols": 2, "force_refresh": True, "cache_tickers": 5})
    monkeypatch.setattr(R, "apply", lambda *a, **k: pytest.fail("dry run reached apply"))
    rc = R.main(["--dry-run", "--snapshot-date", "2026-11-06", "--project-root", str(tmp_path)])
    assert rc == 0
    assert not LR.receipt_path(LANE, state_root).exists()
    printed = capsys.readouterr().out
    assert "DRY-RUN" in printed and "ticker_snapshot_daily" in printed


def test_apply_writes_a_v2_receipt_with_the_verified_count(tmp_path, monkeypatch, state_root):
    monkeypatch.setattr(R, "apply", lambda *a, **k: {
        "snapshot_date": "2026-11-06", "sources": {}, "screens": {}, "symbols": 91, "refreshed": 88,
        "not_refreshed": 2, "rejected_non_ticker": 1, "snapshot_rows_verified": 88,
        "fundamentals_rows": 792, "fundamentals_symbols": 88,
        "skipped": {"not_refreshed": 2, "rejected_non_ticker": 1}})
    rc = R.main(["--apply", "--snapshot-date", "2026-11-06", "--project-root", str(tmp_path)])
    assert rc == 0
    doc = json.loads(LR.receipt_path(LANE, state_root).read_text())
    assert doc["schema"] == "LaneRunReceipt@v2"
    assert doc["produced_count"] == 88 and doc["attempted_count"] == 91
    assert doc["ok_at"] == doc["finished_at"]
    assert doc["output_evidence"][0]["ref"] == "ticker_snapshot_daily"
    assert doc["output_evidence"][1] == {"kind": "store_rows", "ref": "fundamental_data", "source": "finviz",
                                         "rows_written": 792}


def test_apply_that_verified_nothing_exits_non_zero(tmp_path, monkeypatch, state_root):
    monkeypatch.setattr(R, "apply", lambda *a, **k: {
        "snapshot_date": "2026-11-06", "sources": {}, "screens": {}, "symbols": 5, "refreshed": 0,
        "not_refreshed": 5, "rejected_non_ticker": 0, "snapshot_rows_verified": 0,
        "fundamentals_rows": 0, "fundamentals_symbols": 0, "skipped": {"not_refreshed": 5}})
    assert R.main(["--apply", "--snapshot-date", "2026-11-06", "--project-root", str(tmp_path)]) == 1
    doc = json.loads(LR.receipt_path(LANE, state_root).read_text())
    assert doc["status"] == "failed" and doc["produced_count"] == 0
    assert doc["empty_reason"] == "no_refreshed_records"


def test_a_raised_apply_leaves_a_failed_receipt(tmp_path, monkeypatch, state_root):
    def boom(*a, **k):
        raise RuntimeError("db went away")

    monkeypatch.setattr(R, "apply", boom)
    with pytest.raises(RuntimeError, match="db went away"):
        R.main(["--apply", "--snapshot-date", "2026-11-06", "--project-root", str(tmp_path)])
    doc = json.loads(LR.receipt_path(LANE, state_root).read_text())
    assert doc["status"] == "failed" and doc["skipped_reasons"] == {"dependency_unavailable": 1}
    assert doc["produced_count"] == 0


def test_a_bad_snapshot_date_is_refused(tmp_path):
    assert R.main(["--dry-run", "--snapshot-date", "06-11-2026", "--project-root", str(tmp_path)]) == 2
