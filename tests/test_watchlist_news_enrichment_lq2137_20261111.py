"""LQ-20261107-2137: /api/v2/watchlist enrichment reads fail loud as UNKNOWN, and the news read uses a real column.

Production: ``MAX(quality_score)`` on news_articles (a column that does not exist; the table has relevance_score) raised
~every poll, _db_query swallowed it, ``or []`` made it "no news", and every item silently lost the active_news
conviction signal. Hermetic and synthetic: no database or state file is touched.
"""
from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
import db_adapter  # noqa: E402
from lib.data_broker import watch_intelligence  # noqa: E402

T0 = dt.datetime(2026, 11, 11, 12, 0, tzinfo=dt.timezone.utc)
NEWS_COLUMNS = {"symbol", "created_at", "relevance_score", "title"}   # synthetic copy of the real column set (no quality_score)


class FakeDb:
    def __init__(self, fail=None):
        self.fail = fail or {}          # source name -> exception
        self.sql = []

    def execute(self, sql, params=None, fetch="all"):
        self.sql.append(sql)
        if "news_articles" in sql:
            if "quality_score" in sql:      # what Postgres says today
                raise RuntimeError('column "quality_score" does not exist')
            if "news" in self.fail:
                raise self.fail["news"]
            return [{"symbol": "S", "news_count": 5, "top_score": Decimal("0.82")}]
        if "social_sentiment_history" in sql:
            if "social" in self.fail:
                raise self.fail["social"]
            return [{"symbol": "S", "mention_count": 9, "sentiment_score": Decimal("0.3")}]
        return []


@pytest.fixture
def run(monkeypatch):
    def _run(db):
        monkeypatch.setattr(api_v2, "_load_json", lambda p: {"watchlist.json": {"symbols": ["S"]}}.get(Path(p).name))
        monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
        monkeypatch.setattr(db_adapter, "load_watchlist_items", lambda **kw: [])
        monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
        monkeypatch.setattr(db_adapter, "_execute", db.execute)
        monkeypatch.setattr(watch_intelligence, "active_ticker_directives", lambda: [
            {"symbol": "S", "id": 1, "label": "Watchlist", "rationale": None, "trade_ai_enabled": True,
             "hermes_enabled": True, "created_at": T0, "updated_at": None}])
        out = api_v2.watchlist_combined()
        return out, {i["symbol"]: i for i in out["items"]}
    return _run


def _news_sql(db):
    return next(s for s in db.sql if "news_articles" in s)


def test_the_news_query_names_a_column_the_table_has(run):
    db = FakeDb()
    run(db)
    sql = _news_sql(db)
    assert "quality_score" not in sql
    assert "MAX(relevance_score)" in sql and "relevance_score" in NEWS_COLUMNS


def test_a_healthy_read_fills_news_fields_and_earns_the_signal(run):
    out, items = run(FakeDb())
    s = items["S"]
    assert out["enrichment_unknown"] == {}
    assert s["news_7d"] == 5 and float(s["news_top_score"]) == pytest.approx(0.82)
    assert "active_news" in s["conviction_signals"]
    assert "conviction_inputs_unknown" not in s and "news_status" not in s


def test_a_failed_news_read_is_unknown_with_its_reason_not_no_news(run):
    out, items = run(FakeDb(fail={"news": RuntimeError('column "foo" does not exist')}))
    s = items["S"]
    assert "news" in out["enrichment_unknown"] and "does not exist" in out["enrichment_unknown"]["news"]
    assert s["news_status"] == "UNKNOWN" and s["news_7d"] is None and s["news_top_score"] is None
    assert s["conviction_inputs_unknown"] == ["news"]
    assert "active_news" not in s["conviction_signals"]


def test_the_old_query_would_have_been_reported_unknown_not_silent(run):
    # Re-create the shipped defect: a query naming quality_score. The Postgres error must surface, not vanish.
    db = FakeDb()
    db.fail = {"news": RuntimeError('column "quality_score" does not exist')}
    out, items = run(db)
    assert out["enrichment_unknown"]["news"].startswith("RuntimeError: column \"quality_score\"")
    assert items["S"]["news_status"] == "UNKNOWN"


def test_one_failed_source_does_not_mark_the_others_unknown(run):
    out, items = run(FakeDb(fail={"social": RuntimeError("boom")}))
    assert set(out["enrichment_unknown"]) == {"social"}
    s = items["S"]
    assert s["news_7d"] == 5 and "news_status" not in s
    assert s["conviction_inputs_unknown"] == ["social"]


def test_database_disabled_is_unknown_not_empty(run, monkeypatch):
    db = FakeDb()
    out, items = run(db)       # healthy first, to prove the fixture
    assert out["enrichment_unknown"] == {}
    monkeypatch.setattr(db_adapter, "USE_DB", False, raising=False)
    monkeypatch.setattr(api_v2, "_load_json", lambda p: {"watchlist.json": {"symbols": ["S"]}}.get(Path(p).name))
    out2 = api_v2.watchlist_combined()
    assert set(out2["enrichment_unknown"]) >= {"news", "social", "scan", "llm_health"}
