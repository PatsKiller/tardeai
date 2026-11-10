"""LQ-20261107-1817: catalyst_events publish->ingest latency. Backfill is not a new catalyst. Synthetic data only."""
from __future__ import annotations

import importlib
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


def test_threshold_comes_from_config_not_code():
    f = _f()
    assert f.max_age_hours() == 72.0
    assert f.max_age_hours(f._CONFIG.parent / "does_not_exist.json") == f.DEFAULT_MAX_AGE_HOURS


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


def test_news_ingestion_writes_no_catalyst_for_aged_article():
    ni = importlib.import_module("news_ingestion")
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
