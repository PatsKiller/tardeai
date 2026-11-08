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


def _snap(**kw):
    return c.build_snapshot(now=TUE_0555, ticker_snapshot=TICKERS, articles=ARTS, futures=None, llm=None, **kw)


def test_feed_is_newest_first_with_exposure_and_so_what_and_macro_item():
    feed = _snap()["feed"]
    times = [c._ts(i["published_at"]) for i in feed]
    assert times == sorted(times, reverse=True)
    top = next(i for i in feed if i["title"] == "AAA founder plans to sell shares")
    assert top["kind"] == "holding" and top["exposure"] == 1086.0
    assert top["so_what"] == "You hold $1,086 here; AAA is +8.6% since Mon close."
    macro = next(i for i in feed if i["kind"] == "macro")
    assert macro["exposure"] == 0 and "whole book" in macro["so_what"]


def test_same_story_under_two_held_names_is_one_item_with_summed_exposure():
    arts = [{"symbol": s, "title": "Both names hit", "source": "x", "published_at": datetime(2026, 11, 9, 20, 0, tzinfo=ET), "relevance_score": 0.8} for s in ("AAA", "BBB")]
    snap = c.build_snapshot(now=TUE_0555, ticker_snapshot=TICKERS, articles=arts, futures=None, llm=None)
    items = [i for i in snap["feed"] if i["title"] == "Both names hit"]
    assert len(items) == 1 and items[0]["exposure"] == 2042.0 and len(items[0]["holdings"]) == 2


def test_week_ahead_lists_macro_fomc_earnings_exdiv_and_says_fed_speakers_have_no_feed():
    cal = {"dates": {"2026-11-10": {"events": [{"event": "cpi", "name": "Consumer Price Index", "time_et": "08:30"}]},
                     "2026-12-30": {"events": [{"event": "x", "name": "far"}]}}, "fomc_decisions": ["2026-11-11"]}
    wa = c.build_week_ahead(now=TUE_0555, macro_calendar=cal, earnings={"AAA": {"earnings_date": "2026-11-12"}, "ZZZ": {"earnings_date": "2026-11-12"}, "WWW": {"earnings_date": "2027-02-01"}},
                            ex_divs=[{"symbol": "BBB", "ex_date": "2026-11-13"}], held=["AAA", "BBB"], watch=["WWW"])
    assert [(e["date"], e["kind"]) for e in wa["events"]] == [("2026-11-10", "macro"), ("2026-11-11", "fomc"), ("2026-11-12", "earnings"), ("2026-11-13", "ex_div")]
    assert wa["events"][2]["symbols"] == ["AAA"]
    assert "no feed" in wa["fed_speakers"]


def test_cio_brief_pending_until_the_lq1257_file_exists_then_passed_through():
    assert _snap()["cio_brief"] == {"status": "pending", "label": "CIO brief pending"}
    b = _snap(cio_brief={"summary": "s", "risk_tier": "YELLOW", "actions": [{"symbol": "AAA", "action": "raise stop"}]})["cio_brief"]
    assert b["status"] == "available" and b["risk_tier"] == "YELLOW" and b["actions"][0]["action"] == "raise stop"


# ---- LQ-1260: intraday "Today so far" and --if-changed -----------------------------------------------------------
TUE_1030 = datetime(2026, 11, 10, 10, 30, tzinfo=ET)


def _build(now, *, tickers=TICKERS, arts=ARTS, prior=None, llm=None, if_changed=True):
    return c.build_snapshot(now=now, ticker_snapshot=tickers, articles=arts, futures=None, llm=llm, prior=prior, if_changed=if_changed)


def _tick(**pct):
    t = {k: dict(v) for k, v in TICKERS["tickers"].items()}
    for sym, p in pct.items():
        t[sym] = {**t[sym], "quote": {"price": 10.0, "change_pct": p}}
    return {"tickers": t, "_meta": TICKERS["_meta"]}


def test_no_change_skips_without_an_llm_call():
    calls = []
    first = _build(TUE_1030, llm=lambda p: calls.append(p) or "text")
    assert first["updated"]["kind"] == "first" and len(calls) == 1
    again = _build(TUE_1030 + timedelta(minutes=15), prior=first, llm=lambda p: calls.append(p) or "x")
    assert again is None and len(calls) == 1


def test_a_new_held_article_rebuilds_marks_updated_and_may_call_the_llm():
    first = _build(TUE_1030, llm=lambda p: "old words")
    new = {"symbol": "AAA", "title": "AAA names a new CFO", "source": "yahoo_rss", "published_at": TUE_1030 + timedelta(minutes=5), "relevance_score": 0.8}
    calls = []
    snap = _build(TUE_1030 + timedelta(minutes=15), arts=ARTS + [new], prior=first, llm=lambda p: calls.append(p) or "fresh words")
    assert snap["updated"]["kind"] == "news" and snap["updated"]["symbol"] == "AAA"
    assert snap["updated"]["headline"] == "AAA names a new CFO" and snap["updated"]["at_et"] == "10:45 ET"
    assert snap["summary"]["text"] == "fresh words" and len(calls) == 1


def test_a_held_move_crossing_3pct_rebuilds_with_the_reason():
    first = _build(TUE_1030, tickers=_tick(CCC=1.0), llm=lambda p: "t")
    snap = _build(TUE_1030 + timedelta(minutes=15), tickers=_tick(CCC=3.4), prior=first, llm=lambda p: "t2")
    assert snap["updated"]["kind"] == "move" and snap["updated"]["reason"] == "CCC +3.4%"
    # already past 3% last time: a further 1% step is not a new cross
    again = _build(TUE_1030 + timedelta(minutes=30), tickers=_tick(CCC=4.6), prior=snap, llm=lambda p: "t3")
    assert again["updated"] == snap["updated"] and again["summary"]["source"] == "carried" and again["summary"]["text"] == "t2"


def test_watchlist_only_news_rebuilds_data_but_never_spends_a_call():
    first = _build(TUE_1030, llm=lambda p: "kept")
    new = {"symbol": "WWW", "title": "WWW downgraded", "source": "x", "published_at": TUE_1030, "relevance_score": 0.5}
    calls = []
    snap = _build(TUE_1030 + timedelta(minutes=15), arts=ARTS + [new], prior=first, llm=lambda p: calls.append(p) or "no")
    assert snap is not None and not calls and snap["summary"]["text"] == "kept"
    assert any(i["title"] == "WWW downgraded" for i in snap["feed"])


def test_today_section_only_while_the_session_is_open_and_has_news_since_open():
    arts = ARTS + [{"symbol": "AAA", "title": "AAA midday", "source": "x", "published_at": TUE_1030 - timedelta(minutes=30), "relevance_score": 0.9}]
    mid = _build(TUE_1030, arts=arts, if_changed=False)
    assert mid["window"]["session_open"] and mid["today"]["label"] == "Today so far"
    assert [i["title"] for i in mid["today"]["news"]] == ["AAA midday"] and mid["today"]["moves"]
    assert "prior close" in mid["today"]["basis"]
    assert _build(TUE_0555, arts=arts, if_changed=False)["today"] is None
    assert _build(datetime(2026, 11, 10, 16, 5, tzinfo=ET), arts=arts, if_changed=False)["today"] is None


def test_cli_cio_path_is_the_lq1257_runtime_file():
    import since_close_snapshot as cli
    assert str(cli.CIO_BRIEF_REL) == "data/runtime/cio_overnight_brief/latest.json"
