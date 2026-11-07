"""LQ-20261107-63 HERMES_SOCIAL_SENTIMENT_REAL_TEXT: search placeholders are not mentions, zero polarity is no row."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hermes_social_sentiment as hs  # noqa: E402

PLACEHOLDER = {"url": "https://www.reddit.com/r/stocks/comments/abc/", "title": "Link to reddit.com",
               "snippet": "The site owner hides the web page description."}
QUOTE_PAGE = {"url": "https://finance.yahoo.com/quote/NVDA", "title": "NVIDIA Corporation (NVDA) Stock Price",
              "snippet": "Find the latest NVIDIA stock quote, history, news and other vital information."}
BULL = {"url": "https://www.reddit.com/r/stocks/comments/b/", "title": "NVDA breakout looks bullish, buying calls",
        "snippet": "Strong earnings beat and a rally to new highs, upgrade from analysts."}
BEAR = {"url": "https://stocktwits.com/symbol/NVDA", "title": "NVDA crash incoming, selling puts and shorting",
        "snippet": "Overvalued, bearish downgrade, dump expected after the miss."}
NEUTRAL_REAL = {"url": "https://www.reddit.com/r/stocks/comments/c/", "title": "NVDA daily discussion thread for Monday",
                "snippet": "Talk about what you are watching this week in the market."}


def setup_function(_f):
    hs.NORMALIZE_SKIPS.clear()


def test_placeholder_only_results_write_no_row():
    # old behaviour: 6 placeholders -> mention_count 6, 0/0, score 0, conf 0.48 row
    assert hs.normalize("NVDA", [PLACEHOLDER] * 6) is None
    assert hs.NORMALIZE_SKIPS["placeholder_or_non_forum"] == 1


def test_non_forum_quote_pages_are_not_mentions():
    assert hs.normalize("NVDA", [QUOTE_PAGE, QUOTE_PAGE]) is None


def test_real_text_without_bull_bear_words_is_no_row_not_neutral_zero():
    assert hs.normalize("NVDA", [NEUTRAL_REAL, dict(NEUTRAL_REAL, url="https://reddit.com/r/y/2")]) is None
    assert hs.NORMALIZE_SKIPS["no_polarity_evidence"] == 1


def test_mention_count_counts_only_real_forum_items():
    out = hs.normalize("NVDA", [PLACEHOLDER, QUOTE_PAGE, BULL, BEAR, PLACEHOLDER, PLACEHOLDER])
    assert out is not None
    assert out["mention_count"] == 2          # not the page limit (6)
    assert out["bullish_count"] + out["bearish_count"] >= 1
    assert out["confidence"] <= 0.50


def test_single_post_is_thin_evidence_not_a_row():
    assert hs.normalize("NVDA", [BULL]) is None
    assert hs.NORMALIZE_SKIPS["thin_evidence"] == 1


def test_polarity_follows_text():
    assert hs.normalize("NVDA", [BULL, dict(BULL, url="https://reddit.com/r/x/2")])["sentiment_score"] > 0
    assert hs.normalize("NVDA", [BEAR, dict(BEAR, url="https://stocktwits.com/2")])["sentiment_score"] < 0


def test_placeholder_text_is_never_in_the_stored_summary():
    out = hs.normalize("NVDA", [PLACEHOLDER, BULL, BEAR])
    assert "Link to reddit.com" not in out["top_posts_summary"]
    assert "hides the web page" not in out["top_posts_summary"]


def test_persist_never_flags_a_spike_and_keeps_counts_current(monkeypatch):
    seen = {}
    monkeypatch.setattr(hs, "_fence_before_first_write", lambda: None)
    monkeypatch.setattr(hs, "_db_write", lambda sql, params=None: seen.update(sql=sql, params=params) or True)
    sent = hs.normalize("NVDA", [BULL, BEAR, PLACEHOLDER, PLACEHOLDER, PLACEHOLDER, PLACEHOLDER])
    assert hs.persist("NVDA", sent) is True
    params = seen["params"]
    assert params[4] == 2                    # mention_count: the two real items, not 6
    assert params[9] is None and params[10] is False   # volume_zscore NULL, unusual_spike False
    assert "unusual_spike=EXCLUDED.unusual_spike" in seen["sql"]


def test_lane_output_reports_skip_reasons():
    out = hs.lane_output(10, 0, 0, False, {"placeholder_or_non_forum": 7, "no_polarity_evidence": 3})
    assert out["skipped_reasons"]["placeholder_or_non_forum"] == 7
    assert out["skipped_reasons"]["no_polarity_evidence"] == 3
    assert out["produced_count"] == 0
