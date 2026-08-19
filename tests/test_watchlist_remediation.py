"""Unit tests for the 2026-08-19 watchlist remediation.

Covers the two pieces of pure logic added for the watchlist audit:
  - `_sentiment_to_social`: folds social_sentiment_history.sentiment_score (-1..1)
    onto intelligence_entities.social_score (0..100) + a label.
  - source-aware `data_source_stale` retry for the new `social` / `hermes_social`
    liveness keys (Gap E self-healing).
"""
from __future__ import annotations

import json
from pathlib import Path

from health_agent import _data_source_retry_cmd
from sync_social_to_intelligence import _sentiment_to_social

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "config" / "health_agent_policy.json").read_text())


# ── Gap A: sentiment -> social_score fold ────────────────────────────────────

def test_sentiment_neutral_maps_to_50():
    score, label = _sentiment_to_social(0.0)
    assert score == 50.0
    assert label == "neutral"


def test_sentiment_fully_bullish_maps_to_100():
    score, label = _sentiment_to_social(1.0)
    assert score == 100.0
    assert label == "bullish"


def test_sentiment_fully_bearish_maps_to_0():
    score, label = _sentiment_to_social(-1.0)
    assert score == 0.0
    assert label == "bearish"


def test_sentiment_none_is_neutral_default():
    score, label = _sentiment_to_social(None)
    assert score == 50.0
    assert label == "neutral"


def test_sentiment_polarity_labels():
    assert _sentiment_to_social(0.4)[1] == "bullish"
    assert _sentiment_to_social(0.2)[1] == "positive"
    assert _sentiment_to_social(-0.4)[1] == "bearish"
    assert _sentiment_to_social(-0.2)[1] == "negative"


def test_sentiment_out_of_range_is_clamped():
    score, _ = _sentiment_to_social(5.0)
    assert 0.0 <= score <= 100.0
    score2, _ = _sentiment_to_social(-5.0)
    assert 0.0 <= score2 <= 100.0


# ── Gap E: source-aware retry for social lanes ───────────────────────────────

def _cmd(ftype: str, source: str):
    return _data_source_retry_cmd(POLICY, ftype, {"type": ftype, "source": source})


def test_social_source_retries_the_fold_bridge():
    assert _cmd("data_source_stale", "social") == (
        ".venv/bin/python scripts/sync_social_to_intelligence.py --apply"
    )


def test_hermes_social_retries_its_producer():
    assert _cmd("data_source_stale", "hermes_social") == (
        ".venv/bin/python scripts/hermes_social_sentiment.py --apply"
    )


def test_quote_sources_still_use_quote_ingest():
    assert _cmd("data_source_stale", "yahoo_finance") == (
        ".venv/bin/python scripts/external_market_data_ingest.py --quotes"
    )
