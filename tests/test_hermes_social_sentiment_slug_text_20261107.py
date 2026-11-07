"""ANCHOR: HERMES_SOCIAL_SENTIMENT_SLUG_TEXT_20261107 — the thread title survives in the URL.

LQ-20261107-123. The lane's search engines answer every ``site:reddit.com`` query with the literal
title "Link to reddit.com" and the summary "The site owner hides the web page description.". The
2026-11-07 fix (7e787c7ae, LQ-20261107-63) stopped counting those as mentions — correct — but it also
discarded them, and with them the only text the search route ever returns. Measured against the live
SearXNG on 2026-11-07: 8 of 8 symbols produced zero rows, because every reddit item's usable text is
the empty string. The lane went from false data to no data:

    NOC   results=6 substantive=0  row=no   skips={'placeholder_or_non_forum': 1}
    LMT   results=6 substantive=0  row=no
    MSFT  results=6 substantive=0  row=no
    ...

The real thread title is in the URL path — ``/r/stocks/comments/1fxv2h1/defense_stocks_what_happens
_if_the_major_`` — so the placeholder is recoverable rather than fatal. Two further defects were
measured on the same rows: half of the forum hits do not mention the symbol at all (LDOS: 0 of 14,
MAIN: 0 of 25), and the keyword test is a substring test, so "outputs" reads as bearish ("puts"),
"along" as bullish ("long") and "bullet" as bullish ("bull").

Hermetic: synthetic results, a fake ``_searxng``. No network, no DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hermes_social_sentiment as hs  # noqa: E402

# The shape Yandex actually returns for a reddit hit (captured 2026-11-07, read-only).
YANDEX_REDDIT = {
    "url": "https://www.reddit.com/r/stocks/comments/1fxv2h1/defense_stocks_what_happens_if_the_major/",
    "title": "Link to reddit.com",
    "snippet": "The site owner hides the web page description.",
    "engine": "yandex",
}
REDDIT_NAMED_BULL = {
    "url": "https://www.reddit.com/r/stocks/comments/1abc2de/why_lockheed_martin_lmt_might_be_a_smart_buy/",
    "title": "Link to reddit.com",
    "snippet": "The site owner hides the web page description.",
    "engine": "yandex",
}
REDDIT_UNRELATED = {
    "url": "https://www.reddit.com/r/stocks/comments/1j8aimn/trump_set_to_meet_with_wall_st_execs_this_week/",
    "title": "Link to reddit.com",
    "snippet": "The site owner hides the web page description.",
    "engine": "yandex",
}
REDDIT_AD_PAGE = {
    "url": "https://www.reddit.com/advertising/",
    "title": "Financial services ads, trends & insights | Reddit",
    "snippet": "",
    "engine": "bing",
}
QUOTE_PAGE = {
    "url": "https://finance.yahoo.com/quote/LMT/",
    "title": "Lockheed Martin Corporation (LMT) Stock Price, News, Quote",
    "snippet": "Find the latest Lockheed Martin Corporation (LMT) stock quote.",
    "engine": "bing",
}


def setup_function(_f):
    hs.NORMALIZE_SKIPS.clear()


# ── the text that is actually there ──────────────────────────────────────────────────────────────

def test_a_placeholder_hit_still_carries_its_thread_title():
    text = hs.real_text(YANDEX_REDDIT)
    assert text == "defense stocks what happens if the major"
    assert "link to reddit.com" not in text.lower()
    assert "hides the web page" not in text.lower()


def test_the_recovered_text_is_enough_to_be_a_mention():
    """The merged rule dropped every Yandex hit because it had no text; with the slug it has some."""
    assert len(hs.real_text(YANDEX_REDDIT)) >= hs.MIN_TEXT_CHARS
    assert hs.is_substantive_forum_mention(YANDEX_REDDIT) is True


def test_a_url_without_a_thread_slug_yields_nothing():
    assert hs.title_from_url("https://www.reddit.com/advertising/") == ""
    assert hs.title_from_url("") == ""
    assert hs.title_from_url("https://finance.yahoo.com/quote/LMT/") == ""


def test_a_real_title_still_wins_over_the_slug():
    item = dict(YANDEX_REDDIT, title="Northrop Grumman Q3 beat", snippet="")
    assert hs.real_text(item) == "Northrop Grumman Q3 beat"


# ── a mention is about the symbol ────────────────────────────────────────────────────────────────

def test_a_thread_that_does_not_name_the_symbol_is_not_a_mention():
    assert hs.names_symbol(hs.real_text(REDDIT_UNRELATED), "LDOS") is False
    assert hs.normalize("LDOS", [REDDIT_UNRELATED, dict(REDDIT_UNRELATED, url=REDDIT_UNRELATED["url"] + "x")]) is None
    assert hs.NORMALIZE_SKIPS["not_about_the_symbol"] == 1


def test_a_reddit_advertising_page_is_never_a_mention():
    assert hs.normalize("LMT", [REDDIT_AD_PAGE, dict(REDDIT_AD_PAGE)]) is None


def test_a_stocktwits_profile_page_is_not_a_post():
    """The engines answer a symbol query with profile pages whose title merely echoes the query."""
    profile = {"url": "https://stocktwits.com/333Trader", "engine": "bing",
               "title": "Unknown (@333Trader) | Stocktwits LDOS", "snippet": "Stocktwits LDOS"}
    assert hs.mentions_symbol(profile, "LDOS") is False
    assert hs.normalize("LDOS", [profile, dict(profile, url="https://stocktwits.com/Algo_Bear")]) is None


def test_a_stocktwits_symbol_stream_is_a_post_surface():
    stream = {"url": "https://stocktwits.com/symbol/LMT", "engine": "bing",
              "title": "LMT: Lockheed Martin Corp Latest Stock Trades", "snippet": "bullish chatter"}
    assert hs.mentions_symbol(stream, "LMT") is True
    assert hs.is_substantive_forum_mention(stream) is True


def test_a_tracking_parameter_does_not_make_a_page_a_mention():
    other = {"url": "https://stocktwits.com/symbol/MELT?_bhlid=abc&trk=IRDM_story", "engine": "bing",
             "title": "MELT: Direxion Daily Gold Miners Index", "snippet": ""}
    assert hs.mentions_symbol(other, "IRDM") is False


def test_a_quote_page_is_still_not_a_mention_even_when_it_names_the_symbol():
    assert hs.normalize("LMT", [QUOTE_PAGE, dict(QUOTE_PAGE)]) is None
    assert hs.NORMALIZE_SKIPS["placeholder_or_non_forum"] == 1


def test_the_symbol_must_be_a_word():
    assert hs.names_symbol("lmt and lin have outperformed", "LMT") is True
    assert hs.names_symbol("the lmtt index", "LMT") is False


def test_mention_count_is_the_threads_that_name_the_symbol():
    out = hs.normalize("LMT", [REDDIT_NAMED_BULL, REDDIT_UNRELATED, QUOTE_PAGE, REDDIT_AD_PAGE,
                               dict(REDDIT_NAMED_BULL, url=REDDIT_NAMED_BULL["url"] + "9/")])
    assert out is not None
    assert out["mention_count"] == 2          # not the page limit of 6
    assert out["sentiment_score"] > 0
    assert "trump" not in out["top_posts_summary"].lower()


# ── the search keeps the named threads that sort past the cap ───────────────────────────────────

def test_search_forum_keeps_named_threads_beyond_the_first_page(monkeypatch):
    filler = [dict(REDDIT_UNRELATED, url=f"https://www.reddit.com/r/x/comments/aaa{i}/some_other_thread_{i}/")
              for i in range(8)]
    fake = filler + [REDDIT_NAMED_BULL]
    monkeypatch.setattr(hs, "_searxng", lambda q, categories="general": fake)
    monkeypatch.setattr(hs.time, "sleep", lambda s: None)

    got = hs.search_forum("LMT")
    assert [hs.real_text(g) for g in got] == ["why lockheed martin lmt might be a smart buy"]


# ── whole words, not substrings ─────────────────────────────────────────────────────────────────

def test_a_substring_is_not_a_sentiment_word():
    for text in ("quarterly outputs rose", "a bullet list", "along the way", "a shortage of chips",
                 "the seller said"):
        assert hs.classify(text) == (0, 0), text


def test_inflected_polarity_words_still_count():
    assert hs.classify("buys and buying and bought")[0] == 3
    assert hs.classify("puts and shorting and sold")[1] == 3


def test_a_recovered_title_scores():
    """The regression this anchors: the same two threads scored 0/0 before the slug was read."""
    out = hs.normalize("LMT", [REDDIT_NAMED_BULL, dict(REDDIT_NAMED_BULL, url=REDDIT_NAMED_BULL["url"] + "b/")])
    assert out is not None
    assert out["bullish_count"] == 2 and out["sentiment_score"] == 1.0
