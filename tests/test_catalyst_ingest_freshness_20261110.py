"""LQ-20261107-1817: catalyst_events publish->ingest latency. Backfill is not a new catalyst. Synthetic data only."""
from __future__ import annotations

import importlib

import pytest
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)


def _f():
    return importlib.import_module("lib.catalyst_freshness")


def test_old_item_is_backfill_and_recent_is_not():
    f = _f()
    assert f.is_backfill(NOW - timedelta(days=400), now=NOW, max_hours=72)
    assert not f.is_backfill(NOW - timedelta(hours=5), now=NOW, max_hours=72)


def test_rfc822_and_naive_and_unparseable():
    f = _f()
    assert f.is_backfill("Mon, 02 Mar 2026 10:00:00 GMT", now=NOW, max_hours=72)
    assert f.parse_published("2026-11-10T12:00:00").tzinfo is not None
    assert not f.is_backfill("not a date", now=NOW, max_hours=72)
    assert not f.is_backfill(None, now=NOW, max_hours=72)


def test_rfc822_offset_is_honoured():
    f = _f()
    assert f.parse_published("Tue, 10 Nov 2026 10:00:00 -0500") == datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)


def test_zero_disables_gate():
    assert not _f().is_backfill(NOW - timedelta(days=900), now=NOW, max_hours=0)


def test_threshold_comes_from_config():
    f = _f()
    assert f.resolve_limit() == (72.0, "ok")


@pytest.mark.parametrize("text", ["", "{not json", "[]", '"x"', "{}", '{"max_publish_age_hours": -5}',
                                  '{"max_publish_age_hours": "nan"}', '{"max_publish_age_hours": "inf"}',
                                  '{"max_publish_age_hours": "abc"}'])
def test_bad_config_fails_closed_warns_and_flags(tmp_path, caplog, text):
    f = _f()
    p = tmp_path / "c.json"
    p.write_text(text)
    with caplog.at_level("WARNING"):
        assert f.resolve_limit(p) == (f.DEFAULT_MAX_AGE_HOURS, "config_unreadable")
    assert "unreadable" in caplog.text
    # gate stays ON with the fallback
    assert f.is_backfill(NOW - timedelta(days=30), now=NOW, max_hours=f.max_age_hours(p))


def test_missing_config_fails_closed_and_warns(tmp_path, caplog):
    f = _f()
    with caplog.at_level("WARNING"):
        assert f.resolve_limit(tmp_path / "nope.json")[1] == "config_unreadable"
    assert "unreadable" in caplog.text


def test_zero_in_config_is_a_valid_disable(tmp_path):
    f = _f()
    p = tmp_path / "c.json"
    p.write_text('{"max_publish_age_hours": 0}')
    assert f.resolve_limit(p) == (0.0, "ok")


class _N2CCur:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchall(self):
        if "catalyst_type_weights" in self.sql[-1]:
            return []
        return self.rows

    def fetchone(self):
        return (999,)

    def close(self):
        pass


class _N2CConn:
    def __init__(self, rows):
        self.c = _N2CCur(rows)

    def cursor(self):
        return self.c

    def commit(self):
        pass

    def close(self):
        pass


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchone(self):
        return None


class _Conn:
    def __init__(self):
        self.c = _Cur()

    def cursor(self):
        return self.c


def _run_n2c(monkeypatch, rows):
    n2c = importlib.import_module("news_to_catalyst")
    conn = _N2CConn(rows)
    monkeypatch.setattr(n2c, "_get_conn", lambda: conn)
    return n2c, conn, n2c.run(as_json=False)


def test_news_to_catalyst_skips_aged_rows_and_counts(monkeypatch):
    old = datetime(2026, 3, 2, tzinfo=timezone.utc)
    rows = [(1, "EXMP", "watchlist", "Example Corp raises full-year guidance", "s", "t", "u", old)]
    n2c, conn, out = _run_n2c(monkeypatch, rows)
    assert not any("INSERT INTO catalyst_events" in s for s in conn.c.sql)
    assert out["excluded"]["backfill_aged"] == 1
    assert out["created"] == 0 and out["attempted"] == 0
    assert out["config_unreadable"] is False


def test_news_to_catalyst_fresh_row_is_still_inserted(monkeypatch):
    rows = [(2, "EXMP", "watchlist", "Example Corp raises full-year guidance", "s", "t", "u",
             datetime.now(timezone.utc))]
    n2c = importlib.import_module("news_to_catalyst")
    monkeypatch.setattr(n2c, "gate_catalyst_symbol", lambda sym: (True, ""))
    n2c, conn, out = _run_n2c(monkeypatch, rows)
    assert out["excluded"]["backfill_aged"] == 0
    assert any("INSERT INTO catalyst_events" in s for s in conn.c.sql)


def test_news_to_catalyst_bad_config_flags_and_keeps_gate_on(monkeypatch, tmp_path):
    f = _f()
    bad = tmp_path / "c.json"
    bad.write_text("[]")
    monkeypatch.setattr(f, "_CONFIG", bad)
    old = datetime(2026, 3, 2, tzinfo=timezone.utc)
    rows = [(1, "EXMP", "watchlist", "Example Corp raises full-year guidance", "s", "t", "u", old)]
    n2c, conn, out = _run_n2c(monkeypatch, rows)
    assert out["config_unreadable"] is True
    assert out["excluded"]["backfill_aged"] == 1


def test_news_ingestion_logs_gate_error(monkeypatch, capsys):
    ni = importlib.import_module("news_ingestion")
    f = _f()
    monkeypatch.setattr(f, "is_backfill", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ni._FRESH_LIMIT = 72.0
    ni._feed_downstream(_Conn(), "EXMP", "watchlist", {"title": "t", "summary": "s", "source": "x",
                        "published_at": None}, {"relevance_score": 0.1}, {})
    assert "freshness gate failed" in capsys.readouterr().err


def test_news_ingestion_resolves_limit_once(monkeypatch):
    ni = importlib.import_module("news_ingestion")
    f = _f()
    calls = []
    monkeypatch.setattr(f, "resolve_limit", lambda *a, **k: (calls.append(1) or (72.0, "ok")))
    ni._FRESH_LIMIT = None
    for _ in range(5):
        ni._freshness_limit()
    assert len(calls) == 1


def test_news_ingestion_writes_no_catalyst_for_aged_article():
    ni = importlib.import_module("news_ingestion")
    ni._FRESH_LIMIT = None
    conn = _Conn()
    art = {"title": "Example Corp raises full-year guidance", "summary": "guidance raised", "source": "t",
           "published_at": "Mon, 02 Mar 2026 10:00:00 GMT"}
    ni._feed_downstream(conn, "EXMP", "watchlist", art, {"relevance_score": 0.9}, {})
    assert not any("INSERT INTO catalyst_events" in s for s in conn.c.sql)


def test_news_ingestion_still_writes_catalyst_for_fresh_article():
    ni = importlib.import_module("news_ingestion")
    conn = _Conn()
    pub = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    art = {"title": "Example Corp raises full-year guidance", "summary": "guidance raised", "source": "t",
           "published_at": pub}
    ni._feed_downstream(conn, "EXMP", "watchlist", art, {"relevance_score": 0.9}, {})
    assert any("INSERT INTO catalyst_events" in s for s in conn.c.sql)


def test_sec_published_uses_acceptance_time_when_present():
    m = importlib.import_module("lib.sec_filing_events")
    filings = [{"form": "10-Q", "filing_date": "2026-11-09", "accepted_at": "2026-11-09T21:34:19.000Z",
                "accession_number": "0000000000-26-000001", "items": "", "sec_url": ""}]
    ev = m.events_from_filings("EXMP", filings, today=datetime(2026, 11, 10).date())
    assert ev[0]["published_at"].startswith("2026-11-09T21:34:19")


def test_sec_published_falls_back_to_date():
    m = importlib.import_module("lib.sec_filing_events")
    filings = [{"form": "10-Q", "filing_date": "2026-11-09", "accession_number": "x", "items": "", "sec_url": ""}]
    ev = m.events_from_filings("EXMP", filings, today=datetime(2026, 11, 10).date())
    assert ev[0]["published_at"] == "2026-11-09"


def test_sec_evening_et_filing_uses_acceptance_time():
    """Accepted 2026-11-09 23:30 ET = 2026-11-10T04:30Z: UTC date is the next day but the ET filing date matches."""
    m = importlib.import_module("lib.sec_filing_events")
    filings = [{"form": "10-Q", "filing_date": "2026-11-09", "accepted_at": "2026-11-10T04:30:00.000Z",
                "accession_number": "x", "items": "", "sec_url": ""}]
    ev = m.events_from_filings("EXMP", filings, today=datetime(2026, 11, 10).date())
    assert ev[0]["published_at"].startswith("2026-11-10T04:30:00")


def test_sec_offset_style_acceptance_parsed():
    m = importlib.import_module("lib.sec_filing_events")
    filings = [{"form": "10-Q", "filing_date": "2026-11-09", "accepted_at": "2026-11-09T16:00:00-05:00",
                "accession_number": "x", "items": "", "sec_url": ""}]
    ev = m.events_from_filings("EXMP", filings, today=datetime(2026, 11, 10).date())
    assert ev[0]["published_at"].startswith("2026-11-09T21:00:00")


def test_sec_acceptance_far_from_filing_date_falls_back():
    m = importlib.import_module("lib.sec_filing_events")
    filings = [{"form": "10-Q", "filing_date": "2026-11-09", "accepted_at": "2026-06-01T12:00:00Z",
                "accession_number": "x", "items": "", "sec_url": ""}]
    ev = m.events_from_filings("EXMP", filings, today=datetime(2026, 11, 10).date())
    assert ev[0]["published_at"] == "2026-11-09"
