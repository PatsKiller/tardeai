"""G-PRICE-01: price readers skip quarantined (symbol, date) rows.

Rails: quarantine ≠ silent history DELETE; scrub dry-run default; consumers
honor ticker_prices_quarantine (fail-soft if table missing).
"""
from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

from scripts.lib.ticker_price_quarantine import (
    SCHEMA,
    clear_quarantine_cache,
    filter_price_cache,
    filter_prices,
    is_quarantined,
    normalize_pair,
    quarantined_pairs,
)


def test_schema_and_normalize():
    assert SCHEMA == "TickerPriceQuarantineSkip@v1"
    assert normalize_pair("nvda", "2026-05-04") == ("NVDA", "2026-05-04")
    assert normalize_pair("NVDA", date(2026, 5, 4)) == ("NVDA", "2026-05-04")
    assert normalize_pair("NVDA", "2026-05-04T00:00:00+00:00") == ("NVDA", "2026-05-04")
    assert normalize_pair("", "2026-05-04") is None
    assert normalize_pair("NVDA", "") is None


def test_filter_prices_tuple_and_dict():
    q = {("NVDA", "2026-05-04"), ("NVDA", "2026-05-05")}
    rows = [
        ("NVDA", "2026-05-03", 180.0),
        ("NVDA", "2026-05-04", 0.66),
        ("NVDA", date(2026, 5, 5), 0.18),
        ("NVDA", "2026-05-06", 200.0),
        ("AAPL", "2026-05-04", 190.0),
    ]
    kept = filter_prices(rows, q)
    assert [(r[0], str(r[1])[:10], r[2]) for r in kept] == [
        ("NVDA", "2026-05-03", 180.0),
        ("NVDA", "2026-05-06", 200.0),
        ("AAPL", "2026-05-04", 190.0),
    ]

    dict_rows = [
        {"symbol": "NVDA", "price_date": "2026-05-04", "close_price": 0.66},
        {"symbol": "NVDA", "date": "2026-05-06", "close_price": 200.0},
    ]
    kept_d = filter_prices(dict_rows, q)
    assert len(kept_d) == 1
    assert kept_d[0]["close_price"] == 200.0


def test_filter_prices_empty_quarantine_is_noop():
    rows = [("NVDA", "2026-05-04", 0.66)]
    assert filter_prices(rows, set()) == rows


def test_filter_price_cache_strips_quarantined_dates():
    cache = {
        "NVDA": {"2026-05-03": 180.0, "2026-05-04": 0.66, "2026-05-06": 200.0},
        "AAPL": {"2026-05-04": 190.0},
        "_meta": {"NVDA": {"updated": "2026-05-06"}},
    }
    q = {("NVDA", "2026-05-04")}
    out = filter_price_cache(cache, q)
    assert "2026-05-04" not in out["NVDA"]
    assert out["NVDA"]["2026-05-03"] == 180.0
    assert out["NVDA"]["2026-05-06"] == 200.0
    assert out["AAPL"]["2026-05-04"] == 190.0
    assert out["_meta"]["NVDA"]["updated"] == "2026-05-06"


def test_is_quarantined():
    q = {("NVDA", "2026-05-04")}
    assert is_quarantined("nvda", "2026-05-04", q) is True
    assert is_quarantined("NVDA", "2026-05-06", q) is False


class _FakeCursor:
    def __init__(self, explode: bool = False, rows=None):
        self.explode = explode
        self.rows = rows or []
        self.closed = False

    def execute(self, *_a, **_k):
        if self.explode:
            raise RuntimeError("relation ticker_prices_quarantine does not exist")

    def fetchall(self):
        return list(self.rows)

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def rollback(self):
        self.rolled_back = True


def test_quarantined_pairs_failsoft_missing_table():
    clear_quarantine_cache()
    conn = _FakeConn(_FakeCursor(explode=True))
    assert quarantined_pairs(conn) == set()
    assert conn.rolled_back is True


def test_quarantined_pairs_loads_normalized():
    clear_quarantine_cache()
    rows = [("nvda", date(2026, 5, 4)), ("AAPL", "2026-01-02T12:00:00")]
    conn = _FakeConn(_FakeCursor(rows=rows))
    assert quarantined_pairs(conn) == {("NVDA", "2026-05-04"), ("AAPL", "2026-01-02")}


def test_quarantined_pairs_none_conn():
    assert quarantined_pairs(None) == set()


def test_scrub_inserts_quarantine_before_live_delete():
    """Stage B must never DELETE a live row without a prior quarantine INSERT."""
    from scripts import scrub_ticker_price_outliers as scrub

    src = inspect.getsource(scrub.apply_quarantine)
    insert_at = src.find("INSERT INTO ticker_prices_quarantine")
    delete_at = src.find("DELETE FROM ticker_prices WHERE id")
    assert insert_at >= 0, "quarantine INSERT missing from apply_quarantine"
    assert delete_at >= 0, "live DELETE missing from apply_quarantine"
    assert insert_at < delete_at, "DELETE must follow quarantine INSERT"

    # CLI dry-run default: --apply is store_true (off unless passed)
    text = Path(scrub.__file__).read_text(encoding="utf-8")
    assert '"--apply"' in text or "'--apply'" in text
    assert "store_true" in text
    assert "dry run" in text.lower()


def test_portfolio_get_price_skips_quarantined(monkeypatch):
    """portfolio_price_cache.get_price must not return a quarantined bar."""
    clear_quarantine_cache()
    import scripts.portfolio_price_cache as ppc

    monkeypatch.setattr(
        ppc,
        "_quarantined_pairs_failsoft",
        lambda: {("NVDA", "2026-05-04")},
    )
    cache = {"NVDA": {"2026-05-03": 180.0, "2026-05-04": 0.66, "2026-05-06": 200.0}}
    # On the quarantined date, fall back to prior non-quarantined close
    assert ppc.get_price("NVDA", "2026-05-04", cache, fallback_live=False) == 180.0
    assert ppc.get_price("NVDA", "2026-05-06", cache, fallback_live=False) == 200.0


def test_load_price_cache_strips_via_helper(monkeypatch, tmp_path):
    clear_quarantine_cache()
    import scripts.portfolio_price_cache as ppc

    raw = {"NVDA": {"2026-05-04": 0.66, "2026-05-06": 200.0}, "_meta": {}}
    monkeypatch.setattr(ppc, "_db_load_cache", None)
    monkeypatch.setattr(ppc, "_load_cache", lambda _p: dict(raw))
    monkeypatch.setattr(
        ppc,
        "_quarantined_pairs_failsoft",
        lambda: {("NVDA", "2026-05-04")},
    )
    out = ppc.load_price_cache(tmp_path)
    assert "2026-05-04" not in out["NVDA"]
    assert out["NVDA"]["2026-05-06"] == 200.0
