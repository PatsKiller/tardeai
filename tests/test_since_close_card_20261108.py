"""LQ-20261107-1253: the "Since last close" snapshot builder (synthetic fixtures only)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import since_close_card as c  # noqa: E402

ET = ZoneInfo("America/New_York")


def _t(pct, mv=0.0, wk=1.0, sh=0.0):
    return {"quote": {"price": 10.0, "change_pct": pct}, "performance": {"perf_week": wk},
            "holdings_context": {"shares_total": sh, "market_value_total": mv} if mv else {}}


TICKERS = {"tickers": {
    "AAA": _t(8.6, 1086.0, sh=100), "BBB": _t(-4.4, 956.0, sh=50), "CCC": _t(0.0, 5000.0, sh=9),
    "WWW": _t(-18.2), "XXX": _t(0.5)}, "_meta": {"generated_at": "2026-11-09T17:00:00"}}
ARTS = [
    {"symbol": "AAA", "title": "AAA founder plans to sell shares", "source": "yahoo_rss", "published_at": datetime(2026, 11, 9, 20, 0, tzinfo=ET), "relevance_score": 0.9},
    {"symbol": "AAA", "title": "AAA founder plans to sell shares", "source": "dup", "published_at": datetime(2026, 11, 9, 21, 0, tzinfo=ET), "relevance_score": 0.9},
    {"symbol": "AAA", "title": "a", "source": "s", "published_at": datetime(2026, 11, 9, 19, 0, tzinfo=ET), "relevance_score": 0.2},
    {"symbol": "AAA", "title": "b", "source": "s", "published_at": datetime(2026, 11, 9, 19, 5, tzinfo=ET), "relevance_score": 0.3},
    {"symbol": "AAA", "title": "c", "source": "s", "published_at": datetime(2026, 11, 9, 19, 6, tzinfo=ET), "relevance_score": 0.4},
    {"symbol": "AHEAD", "title": "Wall Street swoons amid AI fears", "source": "CNBC", "published_at": datetime(2026, 11, 9, 22, 0, tzinfo=ET)},
    {"symbol": "KOS", "title": "Kosmos (NYSE:KOS) Cut to Hold at Wall Street Zen", "source": "google_news:MarketBeat", "published_at": datetime(2026, 11, 9, 22, 0, tzinfo=ET)},
]
TUE_0555 = datetime(2026, 11, 10, 5, 55, tzinfo=ET)


def test_tuesday_0555_window_is_monday_1600_with_a_fresh_summary():
    calls = []
    snap = c.build_snapshot(now=TUE_0555, ticker_snapshot=TICKERS, articles=ARTS, futures=None,
                            llm=lambda p: calls.append(p) or "Four sentences. One. Two. Three.")
    assert snap["window"]["label"] == "Since Mon 4:00 PM"
    assert snap["window"]["session_date"] == "2026-11-09"
    assert snap["window"]["start"] == "2026-11-09T21:00:00Z"
    assert snap["window"]["session_open"] is False
    assert snap["summary"]["source"] == "llm" and calls
    assert snap["summary"]["generated_at"] == "2026-11-10T10:55:00Z"
    f = c.freshness(snap, now=TUE_0555)
    assert not f["stale"] and f["window_current"]
    assert snap["moves"][0]["close_tag"] == "Mon close"


def test_snapshot_read_after_the_next_close_is_a_stale_window():
    snap = c.build_snapshot(now=TUE_0555, ticker_snapshot=TICKERS, articles=[], futures=None, llm=None)
    assert c.freshness(snap, now=datetime(2026, 11, 10, 16, 30, tzinfo=ET))["window_current"] is False


def test_weekend_window_names_friday_and_session_is_closed():
    w = c.window(datetime(2026, 11, 8, 14, 0, tzinfo=ET))
    assert w["label"] == "Since Fri 4:00 PM" and w["close_tag"] == "Fri close" and not w["session_open"]


def test_midday_session_is_open_so_the_card_collapses():
    assert c.window(datetime(2026, 11, 10, 11, 0, tzinfo=ET))["session_open"] is True
    assert c.window(datetime(2026, 11, 10, 9, 29, tzinfo=ET))["session_open"] is False
    assert c.window(datetime(2026, 11, 10, 16, 0, tzinfo=ET))["session_open"] is False


def test_moves_held_sorted_by_dollar_impact_then_watchlist():
    m = c.build_moves(TICKERS, close_tag="Mon close")
    assert [r["symbol"] for r in m] == ["AAA", "BBB", "CCC", "WWW", "XXX"]
    assert m[0]["dollar_impact"] == 86.0 and m[1]["dollar_impact"] < 0
    assert not m[3]["held"] and m[3]["dollar_impact"] is None


def test_news_top3_by_relevance_deduped_and_no_news_flag_on_big_movers():
    m = c.attach_news(c.build_moves(TICKERS, close_tag="x"), ARTS)
    aaa = next(r for r in m if r["symbol"] == "AAA")
    assert [n["title"] for n in aaa["news"]] == ["AAA founder plans to sell shares", "c", "b"]
    assert not aaa["no_news"]
    assert next(r for r in m if r["symbol"] == "WWW")["no_news"] is True
    assert next(r for r in m if r["symbol"] == "XXX")["no_news"] is False  # small move, no flag


def test_macro_headlines_exclude_single_company_rating_stories_and_futures_pending():
    mac = c.build_macro(ARTS, None)
    assert [h["title"] for h in mac["headlines"]] == ["Wall Street swoons amid AI fears"]
    assert mac["futures"]["status"] == "pending" and mac["futures"]["label"] == "futures feed pending"
    got = c.build_macro(ARTS, {"quotes": [{"symbol": "ES", "change_pct": -0.4}], "as_of": "x"})
    assert got["futures"]["status"] == "available"


def test_summary_cached_15_minutes_then_refreshed():
    m = c.attach_news(c.build_moves(TICKERS, close_tag="x"), ARTS)
    mac = c.build_macro(ARTS, None)
    n = []
    s1 = c.build_summary(m, mac, now=TUE_0555, llm=lambda p: n.append(1) or "text")
    s2 = c.build_summary(m, mac, now=TUE_0555 + timedelta(minutes=10), llm=lambda p: n.append(1) or "new", prior=s1)
    assert s2["source"] == "cache" and s2["text"] == "text" and len(n) == 1
    s3 = c.build_summary(m, mac, now=TUE_0555 + timedelta(minutes=16), llm=lambda p: n.append(1) or "new", prior=s1)
    assert s3["source"] == "llm" and s3["text"] == "new"


def test_summary_falls_back_to_deterministic_lines_never_empty():
    m = c.attach_news(c.build_moves(TICKERS, close_tag="Mon close"), ARTS)
    mac = c.build_macro(ARTS, None)
    for kw in ({"llm": None}, {"llm": lambda p: (_ for _ in ()).throw(RuntimeError("down"))},
               {"llm": lambda p: "x", "calls_today": 99}, {"llm": lambda p: "  "}):
        s = c.build_summary(m, mac, now=TUE_0555, **kw)
        assert s["source"] == "deterministic" and s["text"] is None and s["lines"] and s["reason"]
    assert any("AAA +8.6%" in line for line in s["lines"])


def test_llm_prompt_carries_only_the_three_parts():
    seen = []
    m = c.attach_news(c.build_moves(TICKERS, close_tag="x"), ARTS)
    c.build_summary(m, c.build_macro(ARTS, None), now=TUE_0555, llm=lambda p: seen.append(p) or "ok")
    assert "AAA" in seen[0] and "Wall Street swoons" in seen[0] and "XXX" not in seen[0]  # small unheld mover omitted


def test_route_reads_the_snapshot_file_and_reports_no_snapshot_honestly(tmp_path, monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
    assert api_v2._home_since_close()["status"] == "no_snapshot"
    snap = c.build_snapshot(now=datetime.now(ET), ticker_snapshot=TICKERS, articles=ARTS, futures=None, llm=None)
    import json
    (tmp_path / "since_close_latest.json").write_text(json.dumps(snap))
    got = api_v2._home_since_close()
    assert got["status"] == "ok" and got["moves"] and got["summary"]["lines"]
    assert got["freshness"]["window_current"] is True
    assert "/api/v2/home/since-close" in open(api_v2.__file__).read()
