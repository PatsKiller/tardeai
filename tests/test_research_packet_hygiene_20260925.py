"""Refresh of PR #255: research-packet hygiene that main's stateful thesis loop did not cover.

1. Failed-lane rows (billing/transport errors) are dropped at the source — get_hermes_context —
   so no consumer reads a "[ERROR] HTTP_402" body as research (52 such DeepSeek rows in the
   14 days to 2026-09-25), and a run of failures cannot use up the external-lane limit.
2. The news symbol guard vetoes a headline whose stated 52-week extreme contradicts ours
   (the DIV / Eaton Vance mismatch), without rejecting correctly-mapped 52-week headlines.

Runs without psycopg2 (CI installs only pytest + pyyaml).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_data_access as hda  # noqa: E402
import news_symbol_guard as guard  # noqa: E402


@pytest.mark.parametrize(
    "rec",
    [
        "[ERROR] HTTP_402: policy=FAST model=deepseek-flash returned=None HTTP 402",
        "Error code: 403 - out of credits",
        "run_failed: timeout",
        "Traceback (most recent call last): ...",
        "",
        None,
    ],
)
def test_failure_bodies_are_detected(rec):
    assert hda.lane_row_failed(rec)


def test_real_opinion_is_kept():
    assert not hda.lane_row_failed("GOOGL (Alphabet Inc.) remains a sound holding: ad revenue +12% ...")


def test_get_hermes_context_drops_failed_lanes_and_keeps_limit(monkeypatch):
    rows = [
        {"lane": "deepseek", "recommendation": "[ERROR] HTTP_402 ...", "created_at": "2026-09-25"},
        {"lane": "deepseek", "recommendation": "[ERROR] HTTP_402 ...", "created_at": "2026-09-24"},
        {"lane": "chatgpt", "recommendation": "Hold: margin recovery intact", "created_at": "2026-09-23"},
        {"lane": "grok", "recommendation": "Trim: valuation stretched", "created_at": "2026-09-22"},
        {"lane": "deepseek", "recommendation": "Add on pullback", "created_at": "2026-09-21"},
        {"lane": "chatgpt", "recommendation": "Hold again", "created_at": "2026-09-20"},
    ]
    seen = {}

    def fake_q(sql, params=()):
        if "hermes_external_research" in sql:
            seen["limit"] = params[-1]
            return rows
        return []

    monkeypatch.setattr(hda, "_q", fake_q)
    out = hda.get_hermes_context("V", external_limit=3)
    recs = [e["recommendation"] for e in out["external_lanes"]]
    assert recs == ["Hold: margin recovery intact", "Trim: valuation stretched", "Add on pullback"]
    assert seen["limit"] > 3  # over-fetched so failures can't consume the limit


DIV_HEADLINE = "Eaton Vance Tax Advantaged Div stock hits 52-week high at 27.99 USD"


def test_div_mismatch_is_vetoed_before_the_ticker_token_match():
    ok, why = guard.headline_matches_symbol("DIV", DIV_HEADLINE, reference_52w=(17.10, 19.91))
    assert ok is False and why.startswith("price_conflict_52w_high")


def test_without_reference_behaviour_is_unchanged():
    ok, why = guard.headline_matches_symbol("DIV", DIV_HEADLINE)
    assert ok is True and why == "ticker_token"


def test_correct_52w_headline_is_not_rejected():
    """A true 52-week-high headline sits near OUR 52-week high even when far above spot (RDWR case)."""
    ok, _ = guard.headline_matches_symbol(
        "RDWR", "Radware (RDWR) stock hits 52-week high at 27.40", reference_52w=(18.0, 27.10)
    )
    assert ok is True


@pytest.mark.parametrize(
    "text",
    [
        "Analysts set price target at $410 for Visa (V)",
        "Company announces $2.5 billion offering (V)",
    ],
)
def test_targets_and_deal_sizes_never_trigger_the_veto(text):
    assert guard.price_contradiction(text, reference_52w=(250.0, 380.0)) is None


def test_52w_low_contradiction():
    assert guard.price_contradiction("XYZ touches 52-week low of 3.10", reference_52w=(12.0, 20.0)).startswith(
        "price_conflict_52w_low"
    )


def test_ingest_path_passes_the_reference():
    text = (ROOT / "scripts/news_ingestion.py").read_text(encoding="utf-8")
    assert "fifty_two_week_reference" in text and "reference_52w=ref_52w" in text


def test_legacy_safe_context_dedups_topics():
    text = (ROOT / "scripts/hermes_external_researcher.py").read_text(encoding="utf-8")
    assert "GROUP BY topic" in text and '"occurrences"' in text
