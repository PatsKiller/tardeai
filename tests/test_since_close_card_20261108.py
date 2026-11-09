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


def test_feed_is_ranked_with_exposure_and_so_what_and_macro_item():
    # LQ-20261107-1283 changed the order from newest-first to ranked-by-the-book; the ranking's own ties still run
    # newest first, which the second assertion covers. The rest of the LQ-1253 contract below is unchanged.
    feed = _snap()["feed"]
    scores = [i["score"] for i in feed]
    assert scores == sorted(scores, reverse=True) and [i["rank"] for i in feed] == list(range(1, len(feed) + 1))
    for sc in {i["score"] for i in feed}:
        ts = [c._ts(i["published_at"]) for i in feed if i["score"] == sc]
        assert ts == sorted(ts, reverse=True), f"equal scores ({sc}) are newest first"
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


# ---- LQ-20261107-1282: what printed since the close -------------------------------------------------------------
CLOSE_MON = datetime(2026, 11, 9, 16, 0, tzinfo=ET)   # the window TUE_0555 is about (Mon 16:00 ET)


def _row(sym, session, bar_end, price, pct=None, ref_date="2026-11-09", ref_close=9.0):
    return {"symbol": sym, "session": session, "bar_end": bar_end, "price": price, "change_pct": pct,
            "reference_date": ref_date, "reference_close": ref_close, "reference_basis": "schwab_test"}


def _moves():
    return c.build_moves(TICKERS, close_tag="Mon close")


def test_no_print_after_the_close_says_so_and_keeps_the_close_percentage():
    out = c.attach_extended(_moves(), [], close_date="2026-11-09", close_at=CLOSE_MON, now=TUE_0555)
    aaa = next(m for m in out if m["symbol"] == "AAA")
    assert aaa["extended"] is None and aaa["extended_note"] == "no print since Mon"
    assert aaa["move_now_pct"] == 8.6 and aaa["dollar_impact_now"] == aaa["dollar_impact"]


def test_an_extended_print_dated_to_this_close_is_a_percentage():
    rows = [_row("AAA", "afterhours", datetime(2026, 11, 9, 18, 5, tzinfo=ET), 11.0, 2.5)]
    aaa = next(m for m in c.attach_extended(_moves(), rows, close_date="2026-11-09", close_at=CLOSE_MON, now=TUE_0555) if m["symbol"] == "AAA")
    ext = aaa["extended"]
    assert ext["state"] == "print" and ext["change_pct"] == 2.5 and ext["session_label"] == "after-hours"
    assert ext["printed_text"] == "Mon 6:05 PM ET" and aaa["move_now_pct"] == 2.5
    # $ moved = shares x extended price x pct, not the Friday dollars
    assert abs(aaa["dollar_impact_now"] - (1086.0 / 10.0) * 11.0 * 0.025) < 0.01


def test_a_print_referencing_another_close_is_a_level_never_a_percentage():
    rows = [_row("AAA", "premarket", datetime(2026, 11, 9, 18, 5, tzinfo=ET), 11.0, 2.5, ref_date="2026-11-06")]
    aaa = next(m for m in c.attach_extended(_moves(), rows, close_date="2026-11-09", close_at=CLOSE_MON, now=TUE_0555) if m["symbol"] == "AAA")
    ext = aaa["extended"]
    assert ext["state"] == "level_only" and ext["change_pct"] is None and ext["price"] == 11.0
    assert aaa["move_now_pct"] == 8.6, "a level does not inherit the close percentage"


def test_a_store_row_with_no_change_is_a_level_and_a_pre_close_row_is_not_a_print_since_the_close():
    rows = [_row("AAA", "overnight", datetime(2026, 11, 9, 15, 59, tzinfo=ET), 11.0, 2.5),
            _row("BBB", "overnight", datetime(2026, 11, 9, 22, 0, tzinfo=ET), 9.5, None)]
    out = {m["symbol"]: m for m in c.attach_extended(_moves(), rows, close_date="2026-11-09", close_at=CLOSE_MON, now=TUE_0555)}
    assert out["AAA"]["extended"] is None, "15:59 is before the close"
    assert out["BBB"]["extended"]["state"] == "level_only" and out["BBB"]["extended"]["session_label"] == "overnight"


def test_the_newest_print_wins():
    rows = [_row("AAA", "overnight", datetime(2026, 11, 9, 22, 0, tzinfo=ET), 10.2, 1.0),
            _row("AAA", "premarket", datetime(2026, 11, 10, 5, 0, tzinfo=ET), 10.4, 3.0)]
    aaa = next(m for m in c.attach_extended(_moves(), rows, close_date="2026-11-09", close_at=CLOSE_MON, now=TUE_0555) if m["symbol"] == "AAA")
    assert aaa["extended"]["change_pct"] == 3.0 and aaa["extended"]["session_label"] == "pre-market"


def test_held_chips_sort_by_the_newest_sessions_dollars():
    rows = [_row("CCC", "overnight", datetime(2026, 11, 9, 22, 0, tzinfo=ET), 12.5, 25.0)]   # 5000 held, Friday 0%
    moves = c.sort_by_now(c.attach_extended(_moves(), rows, close_date="2026-11-09", close_at=CLOSE_MON, now=TUE_0555))
    held = [m["symbol"] for m in moves if m["held"]]
    assert held[0] == "CCC", "CCC moved 25% after the close; its Friday dollars were 0"
    assert set(held) == {"AAA", "BBB", "CCC"}


def test_an_unpriced_name_sorts_after_every_priced_one_and_is_never_read_as_zero():
    """A holding whose market value or move the feed did not supply is the last thing the operator is pointed at —
    not a holding worth $0, which would sink a real mover below noise. The rank rule reads it the same way."""
    priced = {"symbol": "BIG", "held": True, "market_value": 10_000, "change_pct": 5.0, "dollar_impact": 500.0}
    unpriced = {"symbol": "UNK", "held": True, "market_value": None, "change_pct": 9.0, "dollar_impact": None}
    tiny = {"symbol": "TINY", "held": True, "market_value": 100, "change_pct": 1.0, "dollar_impact": 1.0}
    assert [m["symbol"] for m in c.sort_by_now([unpriced, tiny, priced])] == ["BIG", "TINY", "UNK"]
    assert c._biggest_holding([unpriced, tiny])["symbol"] == "TINY", "the unpriced name is not the biggest holding"


def test_market_now_reads_futures_and_indices_and_names_what_it_cannot_see():
    rows = [
        _row("/ES", "futures_open", datetime(2026, 11, 9, 18, 45, tzinfo=ET), 7400.0, None),
        _row("/YM", "futures_open", datetime(2026, 11, 9, 18, 44, tzinfo=ET), 51521.0, 0.26),
        _row("$VIX", "overnight", datetime(2026, 11, 9, 18, 40, tzinfo=ET), 17.1, None),
    ]
    blk = c.build_market_now(rows, close_date="2026-11-09", close_at=CLOSE_MON, now=TUE_0555,
                             labels={"/ES": "S&P 500 futures"})
    assert blk["status"] == "available"
    assert [r["symbol"] for r in blk["futures"]] == ["/ES", "/YM"], "FUTURES_ORDER, and only what printed"
    es, ym = blk["futures"]
    assert es["level"] == 7400.0 and es["change_pct"] is None and es["level_only"] and es["label"] == "S&P 500 futures"
    assert ym["change_pct"] == 0.26 and not ym["level_only"]
    assert [r["symbol"] for r in blk["indices"]] == ["$VIX"]
    assert "/NQ" in blk["missing"] and "$SPX" in blk["missing"]
    assert blk["as_of_text"] == "Mon 6:45 PM ET"
    # no overseas level is invented; the row says when each exchange opens, in ET (Tokyo 09:00 JST = Tue 19:00 ET here)
    assert blk["overseas"]["status"] == "no_feed"
    assert [r["label"] for r in blk["overseas"]["rows"]] == ["Nikkei 225", "Hang Seng", "DAX", "FTSE 100"]
    assert blk["overseas"]["rows"][0]["opens_text"] == "opens Tue 7:00 PM ET"
    assert all("level" not in r for r in blk["overseas"]["rows"]), "never a level the host cannot see"


def test_the_futures_block_stops_saying_pending_once_a_print_exists():
    assert _snap()["macro"]["futures"]["status"] == "pending"
    rows = [_row("/ES", "futures_open", datetime(2026, 11, 9, 18, 45, tzinfo=ET), 7400.0, 0.4)]
    snap = c.build_snapshot(now=TUE_0555, ticker_snapshot=TICKERS, articles=ARTS, futures=None, llm=None, extended_rows=rows)
    assert snap["macro"]["futures"]["status"] == "available" and snap["macro"]["futures"]["quotes"][0]["symbol"] == "/ES"
    assert snap["macro"]["now"]["as_of_text"] == "Mon 6:45 PM ET"


def test_if_changed_rebuilds_on_a_new_extended_print_and_not_without_one():
    rows = [_row("AAA", "overnight", datetime(2026, 11, 9, 22, 0, tzinfo=ET), 10.2, 1.0)]
    first = c.build_snapshot(now=TUE_0555, ticker_snapshot=TICKERS, articles=ARTS, futures=None, llm=None,
                             if_changed=True, extended_rows=rows)
    assert first is not None, "first build"
    same = c.build_snapshot(now=TUE_0555 + timedelta(minutes=15), ticker_snapshot=TICKERS, articles=ARTS, futures=None,
                            llm=None, if_changed=True, prior=first, extended_rows=rows)
    assert same is None, "the same print is not a change"
    newer = [*rows, _row("AAA", "premarket", datetime(2026, 11, 10, 5, 0, tzinfo=ET), 10.4, 3.0)]
    moved = c.build_snapshot(now=TUE_0555 + timedelta(minutes=15), ticker_snapshot=TICKERS, articles=ARTS, futures=None,
                             llm=None, if_changed=True, prior=same or first, extended_rows=newer)
    assert moved is not None
    assert next(m for m in moved["moves"] if m["symbol"] == "AAA")["extended"]["change_pct"] == 3.0


def test_a_held_extended_print_crossing_3pct_is_material_once():
    rows = [_row("AAA", "overnight", datetime(2026, 11, 9, 22, 0, tzinfo=ET), 10.4, 4.0)]
    base = c.build_snapshot(now=TUE_0555, ticker_snapshot=TICKERS, articles=ARTS, futures=None, llm=None, if_changed=False)
    snap = c.build_snapshot(now=TUE_0555 + timedelta(minutes=15), ticker_snapshot=TICKERS, articles=ARTS, futures=None,
                            llm=lambda p: "words", prior=base, if_changed=True, extended_rows=rows)
    assert snap["updated"]["kind"] == "move" and snap["updated"]["reason"] == "AAA +4.0% overnight"
    later = [*rows, _row("AAA", "premarket", datetime(2026, 11, 10, 5, 0, tzinfo=ET), 10.5, 4.2)]
    calls = []
    again = c.build_snapshot(now=TUE_0555 + timedelta(minutes=30), ticker_snapshot=TICKERS, articles=ARTS, futures=None,
                             llm=lambda p: calls.append(p) or "x", prior=snap, if_changed=True, extended_rows=later)
    assert again["summary"]["source"] == "carried" and not calls, "already past 3%: a further print spends nothing"


# ---- LQ-20261107-1283: one story per feed, ranked by the book ----------------------------------------------------
def _rank_arts():
    return [
        {"symbol": "AAA", "title": "AAA founder plans to sell shares", "source": "yahoo_rss",
         "published_at": datetime(2026, 11, 9, 20, 0, tzinfo=ET), "relevance_score": 0.9},
        {"symbol": "BBB", "title": "BBB 13F: acquired by a family office", "source": "google_news:X",
         "published_at": datetime(2026, 11, 9, 20, 1, tzinfo=ET), "relevance_score": 0.9},
        {"symbol": "CCC", "title": "CCC lands a defence contract", "source": "google_news:Y",
         "published_at": datetime(2026, 11, 9, 20, 2, tzinfo=ET), "relevance_score": 0.9},
    ]


def test_feed_is_ranked_by_the_book_and_sinks_appraisal_boilerplate():
    feed = c.build_feed(*_feed_parts(_rank_arts()))
    assert [i["rank"] for i in feed[:3]] == [1, 2, 3]
    assert feed[0]["title"] == "AAA founder plans to sell shares", "$93 moved on a held name outranks boilerplate"
    assert feed[0]["score"] >= feed[1]["score"] >= feed[2]["score"]
    assert any("13F" in i["why"] for i in feed if i["title"].startswith("BBB"))


def test_a_cio_action_lifts_a_flat_name_and_the_dollars_still_come_first():
    """The order the lead asked for: held $ x move FIRST, then the stop/at-risk names. A CIO row lifts a name that
    moved nothing above unrelated noise, and it does not outrank the biggest dollar move in the book."""
    brief = {"stop_advice": [{"symbol": "CCC", "answer": "ADD_STOP", "held_qty": 9}, {"symbol": "BBB", "answer": "HOLD"}]}
    arts = _rank_arts() + [{"symbol": "XXX", "title": "XXX appoints a new treasurer", "source": "google_news:Z",
                            "published_at": datetime(2026, 11, 9, 20, 3, tzinfo=ET), "relevance_score": 0.9}]
    feed = c.build_feed(*_feed_parts(arts), cio_actions=c._cio_actions(brief), at_risk=c._at_risk(brief))
    rank = {i["title"].split()[0]: i["rank"] for i in feed}
    assert rank["AAA"] == 1, "$93 moved on a held name is still first"
    assert rank["CCC"] < rank["XXX"], "the CIO action lifts CCC (0% move) above a nil story on a watchlist name"
    ccc = next(i for i in feed if i["title"].startswith("CCC"))
    assert ccc["why"] == "CIO: CCC ADD_STOP"
    assert c._cio_actions({"stop_advice": [{"symbol": "BBB", "answer": "HOLD"}]}) == {}, "HOLD is not an action"
    # LQ-20261107-1386: a stop_advice row is not a stop proximity. With no stop_now and no ATR there is nothing to
    # measure, so BBB is not at risk and the ranking uses its since-close move text (the old "wider tier" labelled
    # every HOLD row "at its stop", which is the defect this line used to pin).
    assert c._at_risk({"stop_advice": [{"symbol": "BBB", "answer": "HOLD"}]}) == []
    measured = [{"symbol": "BBB", "price": 10.0, "atr": 0.5}]
    near = {"stop_advice": [{"symbol": "BBB", "answer": "HOLD", "stop_now": 9.8}]}
    assert c._at_risk(near, measured) == ["BBB"], "a HOLD row within 1 ATR of a working stop is the risk tier"


def test_one_story_from_two_feeds_is_one_item_listing_both_sources():
    arts = [
        {"symbol": "AAA", "title": "AAA shares surge after an earnings beat - Yahoo Finance", "source": "google_news:Yahoo Finance",
         "published_at": datetime(2026, 11, 9, 20, 0, tzinfo=ET), "relevance_score": 0.8},
        {"symbol": "AAA", "title": "AAA shares surge after an earnings beat | Reuters", "source": "yahoo_rss",
         "published_at": datetime(2026, 11, 9, 20, 5, tzinfo=ET), "relevance_score": 0.8},
    ]
    feed = c.build_feed(*_feed_parts(arts))
    hits = [i for i in feed if "earnings beat" in i["title"]]
    assert len(hits) == 1 and set(hits[0]["sources"]) == {"google_news:Yahoo Finance", "yahoo_rss"}


def _feed_parts(arts):
    """(moves, macro) for build_feed straight, without building a whole snapshot."""
    return c.attach_news(c.build_moves(TICKERS, close_tag="Mon close"), arts), c.build_macro(arts, None)


# ---------------------------------------------------------------- mockup v3: the heat-map glow, computed here
def _glow(arts, tickers=None):
    moves = c.attach_news(c.build_moves(tickers or TICKERS, close_tag="Mon close"), arts)
    feed = c.build_feed(moves, c.build_macro(arts, None))
    return {i["title"]: (i["urgency"], i["urgency_why"]) for i in feed}


def _art(sym, title, at=20):
    return {"symbol": sym, "title": title, "source": "s", "published_at": datetime(2026, 11, 9, at, 0, tzinfo=ET)}


def test_glow_red_for_a_held_name_three_percent_down_since_the_close():
    g = _glow([_art("BBB", "BBB shares slide")])
    assert g["BBB shares slide"][0] == "red"
    assert "held BBB -4.4% since the close" == g["BBB shares slide"][1]
    # 1-2% down is noise, not urgency: no glow, so the operator's eye is not pulled to every small loss
    assert c.urgency_for({"title": "t", "holdings": [{"symbol": "T", "held": True, "change_pct": -1.6}]}) == (None, None)


def test_glow_red_for_a_downgrade_headline_even_when_the_hold_is_flat():
    g = _glow([_art("CCC", "Craig Hallum downgrades CCC to Hold")])
    assert g["Craig Hallum downgrades CCC to Hold"] == ("red", "downgrade / cut")


def test_glow_red_for_a_watchlist_name_ten_percent_down():
    g = _glow([_art("WWW", "WWW plunges on guidance")])
    assert g["WWW plunges on guidance"][0] == "red" and "watchlist WWW -18.2%" == g["WWW plunges on guidance"][1]


def test_glow_amber_for_an_insider_sale_ahead_of_a_big_gain():
    g = _glow([_art("AAA", "AAA founder plans to sell 250,000 shares")])
    assert g["AAA founder plans to sell 250,000 shares"] == ("amber", "insider sale"), "an insider sale outranks the +8.6%"


def test_glow_amber_for_a_held_name_weak_on_the_week():
    tickers = {"tickers": {**TICKERS["tickers"], "CCC": _t(0.0, 5000.0, wk=-8.8, sh=9)}}
    g = _glow([_art("CCC", "CCC holds steady into the weekend")], tickers=tickers)
    assert g["CCC holds steady into the weekend"] == ("amber", "held CCC -8.8% on the week")


def test_glow_green_for_a_big_gain_on_a_holding():
    g = _glow([_art("AAA", "AAA wins a defence contract")])
    assert g["AAA wins a defence contract"] == ("green", "held AAA +8.6% since the close")


def test_boilerplate_never_glows_and_a_quiet_story_stays_dark():
    g = _glow([_art("AAA", "AAA sees a modest fair value lift"), _art("XXX", "XXX names a new director", at=21)])
    assert g["AAA sees a modest fair value lift"] == (None, None), "13F/fair-value boilerplate never glows"
    assert g["XXX names a new director"] == (None, None)


def test_the_urgency_rule_travels_in_the_snapshot():
    rule = _snap()["feed_rule"]
    assert set(rule["urgency"]) == {"red", "amber", "green", "none"}
    assert "3% or more down" in rule["urgency"]["red"]
    assert "insider sale" in rule["urgency"]["amber"]
    assert "3% or more up" in rule["urgency"]["green"]
    assert "score" in rule and "CIO brief action" in rule["score"]
