"""Scalp lane bulk catalyst read (operator 2026-10-09: "build the finviz API fix").

The 5-min lane stalled because each catalyst-cache miss cost ~2 throttled Finviz page requests (measured 4.7 s a
ticker, ~360 s for 76 names). scripts/scalp_catalyst_bulk.py reads data-broker news plus the Finviz Elite news export
for many tickers per request (measured 8 requests, 17.7 s, 64 of 76 covered) and shapes results with the same
build_enrichment the per-ticker path uses. Fakes only: no network, no database.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import catalyst_enrichment as ce  # noqa: E402
import scalp_catalyst_bulk as b  # noqa: E402

CFG = {"bulk_enabled": True, "source_order": ["data_broker_news", "finviz_elite_news_bulk"], "fill_gaps_only": False,
       "db_news_max_age_hours": 72, "db_news_per_symbol": 6, "finviz_news_url": "https://example.invalid/news_export.ashx",
       "finviz_news_view": 3, "finviz_batch_size": 2, "finviz_per_symbol": 10, "finviz_timezone": "America/New_York",
       "per_ticker_fallback_max": 8}


class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def csv_rows(*rows):
    head = '"Title","Source","Date","Url","Category","Ticker"\n'
    return head + "".join(f'"{t}","Wire","{d}","https://x/{i}","Stock","{tk}"\n' for i, (t, d, tk) in enumerate(rows))


def test_build_enrichment_is_the_per_ticker_shape(monkeypatch):
    raw = [{"title": "WFF wins FDA approval for lead drug", "summary": "", "url": "u", "source": "Wire",
            "published_at": ce._now_utc().isoformat(), "provider": "finviz_news"}]
    monkeypatch.setattr(ce, "_fetch_alpha_vantage", lambda s: [])
    monkeypatch.setattr(ce, "_fetch_finviz_news", lambda s: list(raw))
    monkeypatch.setattr(ce, "_fetch_yahoo_news", lambda s: [])
    a, c = ce.enrich_ticker("WFF"), ce.build_enrichment("WFF", list(raw))
    for k in ("catalysts", "catalyst_tier", "catalyst_count", "has_fresh_catalyst", "sources_hit"):
        assert a[k] == c[k], k
    assert set(a) == set(c)


def test_bulk_batches_maps_tickers_and_converts_exchange_time(monkeypatch):
    monkeypatch.setenv("FINVIZ_API_TOKEN", "tok")
    urls = []

    def get(url, **k):
        urls.append(url)
        if "AAA,BBB" in url:
            return Resp(200, csv_rows(("AAA and BBB sign merger agreement", "2026-10-09 15:21:00", "AAA,BBB")))
        return Resp(200, csv_rows(("CCC prices $5M registered direct offering", "2026-10-09 09:05:00", "CCC")))

    out, st = b.enrich_bulk(["aaa", "BBB", "CCC", "DDD"], dict(CFG, source_order=["finviz_elite_news_bulk"]), http_get=get)
    assert st["finviz_calls"] == 2 and len(urls) == 2                      # 4 names, batch 2
    assert "v=3&t=AAA,BBB&auth=tok" in urls[0]
    assert set(out) == {"AAA", "BBB", "CCC"} and st["uncovered"] == ["DDD"]
    art = out["AAA"]["catalysts"][0]
    assert art["published_at"] == "2026-10-09T19:21:00Z"                   # 15:21 ET = 19:21 UTC
    assert out["CCC"]["catalyst_count"] == 1 and out["CCC"]["top_catalyst"]["provider"] == "finviz_news"


def test_rate_limit_stops_further_requests(monkeypatch):
    monkeypatch.setenv("FINVIZ_API_TOKEN", "tok")
    seen = []

    def get(url, **k):
        seen.append(url)
        return Resp(429)
    out, st = b.enrich_bulk(["A", "B", "C", "D", "E"], dict(CFG, source_order=["finviz_elite_news_bulk"]), http_get=get)
    assert len(seen) == 1 and st["finviz_error"] == "HTTP 429" and out == {}
    assert st["uncovered"] == ["A", "B", "C", "D", "E"]


def test_no_token_means_no_finviz_request(monkeypatch):
    monkeypatch.delenv("FINVIZ_API_TOKEN", raising=False)
    out, st = b.enrich_bulk(["A"], dict(CFG, source_order=["finviz_elite_news_bulk"]),
                            http_get=lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert out == {} and st["finviz_calls"] == 0


def test_data_broker_news_is_read_in_one_query_and_merged(monkeypatch):
    monkeypatch.delenv("FINVIZ_API_TOKEN", raising=False)
    q = []

    def db_query(sql, params=None, fetch="all"):
        q.append((sql, params))
        from datetime import timedelta, timezone
        now = ce._now_utc().astimezone(timezone(timedelta(hours=-4)))   # Postgres hands back the session zone
        return [{"symbol": "AAA", "title": "AAA beats Q3 earnings estimates, raises guidance", "source": "yahoo_rss", "source_url": "u1",
                 "published_at": now},
                {"symbol": "AAA", "title": "AAA beats Q3 earnings estimates, raises guidance - Yahoo Finance", "source": "google_news",
                 "source_url": "u2", "published_at": now}]
    out, st = b.enrich_bulk(["AAA", "ZZZ"], CFG, db_query=db_query)
    assert len(q) == 1 and "FROM news_articles" in q[0][0] and q[0][1][0] == ["AAA", "ZZZ"]
    assert out["AAA"]["catalyst_count"] == 1                                # same headline from two feeds collapses
    assert out["AAA"]["has_fresh_catalyst"] is True                         # -04:00 timestamp read as fresh
    assert st["covered"]["data_broker_news"] == 1 and st["uncovered"] == ["ZZZ"]


def test_never_raises():
    out, st = b.enrich_bulk(["A"], dict(CFG, source_order=["data_broker_news"]),
                            db_query=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert out == {} and "error" in st and st["uncovered"] == ["A"]


def test_config_and_wiring():
    cfg = b.load_config(ROOT)
    assert cfg["bulk_enabled"] is True and cfg["source_order"] == ["data_broker_news", "finviz_elite_news_bulk"]
    assert 1 <= cfg["finviz_batch_size"] <= 20 and cfg["per_ticker_fallback_max"] >= 0
    src = (ROOT / "scripts/continuous_runner.py").read_text(encoding="utf-8")
    assert "bulk_catalysts: Optional[Dict] = None" in src
    assert "bulk, bstats = enrich_bulk(list(due), bulk_catalysts)" in src
    assert "miss, deferred = left[:cap], left[cap:]" in src
    lane = (ROOT / "scripts/run_trade_ai_scalp_live.py").read_text(encoding="utf-8")
    assert "bulk_catalysts=bulk_catalysts()" in lane
