"""ANCHOR: SINCE_CLOSE_POSITION_DEDUPE_LQ1387_20261108 — a position is counted once, however many feed copies
carry the story.

2026-11-08, 23:06 ET. The Home since-close feed printed "$760 moved" on a Visa item whose one position had moved
about $380, "$218 moved" for a $109 PFE move, and "$483 moved" for a $243 ANET move. The cause is not the account
count: ``_title_key`` deliberately folds a publisher suffix ("Story" and "Story - Yahoo Finance") into ONE item, and
``build_feed`` appended a holdings entry for every news row — so two feed copies of one story appended the same
position twice, and ``rank_feed`` summed both. ``exposure`` and the item's "So what" were doubled the same way.

A name held in two accounts is still ONE move: ``build_moves`` carries ``holdings_context.market_value_total``
(V, 2026-11-08: rollover + roth, market_value_total 43,202.23 — one move, not two). So the invariant is one entry per
symbol per item, and the rank's dollar sum reads that invariant defensively.

Synthetic fixtures shaped on the served snapshot's own shape (the titles below are the live duplicates). No DB, no
network, no live file is read.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import since_close_card as c  # noqa: E402

ET = ZoneInfo("America/New_York")


def _move(symbol, price, pct, mv, *, now_pct=None, news=(), atr=None):
    rec = {
        "symbol": symbol, "held": True, "price": price, "change_pct": pct, "week_pct": 1.0,
        "dollar_impact": round(mv * pct / 100.0, 2) if mv else None, "market_value": mv or None, "close_tag": "Fri close",
        "big_move": abs(pct) >= 3, "news": list(news),
    }
    if now_pct is not None:
        rec["move_now_pct"] = now_pct
    if atr is not None:
        rec["atr"] = atr
    return rec


def _art(symbol, title, source, minute=0):
    return {"symbol": symbol, "title": title, "source": source,
            "published_at": datetime(2026, 11, 9, 20, minute, tzinfo=ET), "relevance_score": 0.9}


def _news(symbol, title, sources):
    """The move's own news list, as ``attach_news`` leaves it: one row per feed copy, at most three."""
    return [_art(symbol, t, s, i) for i, (t, s) in enumerate(sources)]


#: Exactly the 2026-11-08 duplication: the same story with and without a publisher suffix.
V_STORY = "Visa (V) Q4 Earnings Justified Strong Growth But Left Valuation Questions"
V_MOVE = _move("V", 422.65, 0.01, 43202.23, now_pct=0.88,
               news=_news("V", V_STORY, [(V_STORY, "yahoo_rss"),
                                         (V_STORY + " - Yahoo Finance", "google_news:Yahoo Finance")]))
PFE_STORY = "Pfizer (PFE) Maps Out $650 Million Connecticut Center For Global Clinical Trials"
PFE_MOVE = _move("PFE", 29.39, -1.64, 29460.00, now_pct=0.37,
                 news=_news("PFE", PFE_STORY, [(PFE_STORY, "yahoo_rss"),
                                               (PFE_STORY + " - Yahoo Finance", "google_news:Yahoo Finance")]))
SINGLE_STORY = "T-Mobile raises its guidance for the year"
T_MOVE = _move("T", 21.63, -0.87, 43500.00, now_pct=0.55,
               news=_news("T", SINGLE_STORY, [(SINGLE_STORY, "yahoo_rss")]))


def _feed(moves):
    return c.build_feed(moves, {})


def _item(feed, symbol):
    return next(i for i in feed if any(h["symbol"] == symbol for h in i["holdings"]))


# ---- the item carries one position per symbol ---------------------------------------------------------------
def test_two_feed_copies_of_one_story_are_one_item_with_one_position():
    feed = _feed([V_MOVE])
    assert len(feed) == 1
    item = feed[0]
    assert item["sources"] == ["yahoo_rss", "google_news:Yahoo Finance"], "both sources are still credited"
    assert len(item["holdings"]) == 1, "one position, not one per feed copy"
    assert item["holdings"][0]["symbol"] == "V"


def test_the_items_dollar_move_is_the_books_move_not_twice_it():
    """V: 43,202.23 x 0.88% = $380.18. The live card printed $760."""
    item = _item(_feed([V_MOVE]), "V")
    price = 43202.23 * 0.88 / 100.0
    assert item["why"].startswith(f"${price:,.0f} moved"), item["why"]
    assert f"${price * 2:,.0f} moved" not in item["why"]


def test_the_items_exposure_is_the_books_exposure_not_twice_it():
    item = _item(_feed([V_MOVE]), "V")
    assert item["exposure"] == 43202.23
    assert "You hold $43,202 here" in item["so_what"]


def test_the_rank_note_names_the_real_move():
    item = _item(_feed([PFE_MOVE]), "PFE")
    assert "$109 moved" in item["why"], item["why"]


def test_a_single_copy_is_untouched():
    item = _item(_feed([T_MOVE]), "T")
    assert item["holdings"][0]["symbol"] == "T" and len(item["holdings"]) == 1
    assert item["why"].startswith(f"${43500.00 * 0.55 / 100.0:,.0f} moved"), item["why"]


def test_a_name_in_two_accounts_is_one_move():
    """``build_moves`` aggregates the accounts into market_value_total; nothing downstream may split or double it."""
    snap = {"tickers": {"V": {"quote": {"price": 422.65, "change_pct": 0.01},
                              "performance": {"perf_week": 1.0},
                              "holdings_context": {"accounts": ["schwab_rollover_ira", "schwab_roth"],
                                                   "shares_total": 101.2948, "market_value_total": 43202.23}}}}
    moves = c.build_moves(snap, close_tag="Fri close")
    assert len(moves) == 1 and moves[0]["market_value"] == 43202.23, "one move per symbol, the account total"
    assert moves[0]["held"] is True


# ---- the rank reads the invariant defensively --------------------------------------------------------------
def test_rank_feed_counts_a_duplicated_entry_once_even_if_a_caller_hands_it_two():
    """The fix is at construction, but the sum is where the money is printed, so it holds the line too."""
    dup = {"title": "A story", "kind": "holding", "source": "wire", "published_at": "2026-11-09T01:00:00Z",
           "holdings": [
               {"symbol": "V", "held": True, "market_value": 43202.23, "change_pct": 0.01, "move_now_pct": 0.88},
               {"symbol": "V", "held": True, "market_value": 43202.23, "change_pct": 0.01, "move_now_pct": 0.88},
           ]}
    ranked = c.rank_feed([dup])
    assert ranked[0]["why"].startswith("$380 moved"), ranked[0]["why"]


def test_rank_feed_still_adds_two_different_symbols():
    two = {"title": "A story", "kind": "holding", "source": "wire", "published_at": "2026-11-09T01:00:00Z",
           "holdings": [
               {"symbol": "V", "held": True, "market_value": 1000.0, "change_pct": 1.0},
               {"symbol": "PFE", "held": True, "market_value": 1000.0, "change_pct": 1.0},
           ]}
    assert c.rank_feed([two])[0]["why"].startswith("$20 moved"), "two positions, two dollars"


# ---- the shape of the served snapshot, end to end ----------------------------------------------------------
def test_build_snapshot_prints_the_books_move_for_2026_11_08():
    """The producer's own path: two copies of the V story fold into one item carrying one position, and the card
    prints $380 -- not the $760 the live 04:15Z card printed. PFE is the same story; T is a single copy."""
    tickers = {
        "V": {"quote": {"price": 422.65, "change_pct": 0.01}, "performance": {"perf_week": 1.0},
              "holdings_context": {"accounts": ["schwab_rollover_ira", "schwab_roth"],
                                   "shares_total": 101.2948, "market_value_total": 43202.23}},
        "PFE": {"quote": {"price": 29.39, "change_pct": -1.64}, "performance": {"perf_week": 1.0},
                "holdings_context": {"shares_total": 1000, "market_value_total": 29460.00}},
        "T": {"quote": {"price": 21.63, "change_pct": -0.87}, "performance": {"perf_week": 1.0},
              "holdings_context": {"shares_total": 2000, "market_value_total": 43500.00}},
    }
    articles = ([_art("V", V_STORY, "yahoo_rss", 0), _art("V", V_STORY + " - Yahoo Finance", "google_news:Yahoo Finance", 1),
                 _art("PFE", PFE_STORY, "yahoo_rss", 2), _art("PFE", PFE_STORY + " - Yahoo Finance", "google_news:Yahoo Finance", 3),
                 _art("T", SINGLE_STORY, "yahoo_rss", 4)])
    # the overnight prints the live snapshot carries (move_now_pct), so the dollars are the since-close ones
    def _row(symbol, pct, price, close):
        return {"symbol": symbol, "session": "overnight", "bar_end": datetime(2026, 11, 10, 1, 0, tzinfo=ET),
                "price": price, "change_pct": pct, "reference_date": "2026-11-09", "reference_close": close,
                "reference_basis": "schwab_test"}
    rows = [_row("V", 0.88, 426.4, 422.65), _row("PFE", 0.37, 29.50, 29.39), _row("T", 0.55, 21.75, 21.63)]
    snap = c.build_snapshot(now=datetime(2026, 11, 10, 5, 55, tzinfo=ET),
                            ticker_snapshot={"tickers": tickers, "_meta": {"generated_at": "2026-11-09T17:00:00"}},
                            articles=articles, futures=None, llm=None, extended_rows=rows)
    by_symbol = {i["holdings"][0]["symbol"]: i for i in snap["feed"]}
    v = by_symbol["V"]
    assert "$380 moved" in v["why"] and "$760 moved" not in v["why"], v["why"]
    assert v["exposure"] == 43202.23 and "You hold $43,202 here" in v["so_what"]
    assert len(v["holdings"]) == 1 and set(v["sources"]) == {"yahoo_rss", "google_news:Yahoo Finance"}
    assert sum(1 for i in snap["feed"] if i["holdings"][0]["symbol"] == "V") == 1, "one item, one position"
