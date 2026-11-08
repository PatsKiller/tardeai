"""LQ-20261107-530 (RESEARCH_LANE_REFUSAL_LQ530_20261107): a refusal is neither ok nor a lane error.

The grok research lane fired "error_streak" and "error_rate_24h" while its rows were model refusals:
the writer stored a declining answer as status='refused' (or as "[REJECTED_DATA_QUALITY] llm_refusal"),
and research_lane_health counted the first as a successful non-error row and the second as a lane error.
Both directions measured the same thing, a refusal, and neither was lane breakage.

These tests pin evaluate_lane's bucketing: a refusal row is counted in ``refused_24h`` only, never in
``non_error_24h`` and never in ``error_24h`` nor in the error streak. A real success and a real lane error
keep their meaning. Synthetic fixtures only: no DB, no network, no live row. The repo is PUBLIC.
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib.research_lane_health import consecutive_error_streak, evaluate_lane

NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)

REFUSAL_TEXT = (
    "I cannot recommend or approve market action, generate verdicts, setups or entry levels "
    "for XYZ. I can review the evidence provided and identify risks."
)
REAL_THESIS = "XYZ thesis: hold while the 50-day average holds; invalidation below the prior low."


def _row(rec, status="sent", t="2026-11-07T12:00:00+00:00"):
    return {"recommendation": rec, "status": status, "created_at": t}


def test_refused_status_row_is_not_an_ok_row_and_is_counted_as_refused():
    rows = [_row(REFUSAL_TEXT, status="refused")]
    out = evaluate_lane("grok", newest_first=rows, last_24h=rows, now=NOW)
    assert out["non_error_24h"] == 0, "a refusal stored as status=refused must not count as research"
    assert out["error_24h"] == 0, "a refusal is not a lane error either"
    assert out["refused_24h"] == 1


def test_legacy_sent_row_carrying_refusal_text_is_a_refusal_not_research():
    # Rows written before the writer classified refusals sit in the 24h window as status='sent'.
    rows = [_row(REFUSAL_TEXT, status="sent")]
    out = evaluate_lane("grok", newest_first=rows, last_24h=rows, now=NOW)
    assert out["non_error_24h"] == 0
    assert out["refused_24h"] == 1


def test_rejected_llm_refusal_row_is_a_refusal_not_a_lane_error():
    rej = _row("[REJECTED_DATA_QUALITY] llm_refusal", status="rejected_data_quality")
    rows = [rej, rej, rej, rej, rej]
    out = evaluate_lane("grok", newest_first=rows, last_24h=rows, now=NOW)
    assert out["error_streak"] == 0, "five refusals in a row are not a five-error streak"
    assert out["error_24h"] == 0
    assert out["error_rate_24h"] == 0.0
    assert out["refused_24h"] == 5
    assert not any(f.startswith("error_streak") for f in out["firing"])
    assert not any(f.startswith("error_rate_24h") for f in out["firing"])


def test_all_refusal_day_fires_zero_non_error_not_an_error_rate():
    # The grok shape on 2026-11-07: every attempt in 24h was a refusal. The lane produced no research,
    # so the honest alarm is "zero non-error in 24h", with the refusals named, not a 51% error rate.
    rows = [_row(REFUSAL_TEXT, status="refused") for _ in range(20)]
    rows += [_row("[REJECTED_DATA_QUALITY] llm_refusal", status="rejected_data_quality") for _ in range(20)]
    out = evaluate_lane("grok", newest_first=rows, last_24h=rows, now=NOW)
    assert out["non_error_24h"] == 0
    assert out["refused_24h"] == 40
    assert out["attempts_24h"] == 40
    assert "zero_non_error_24h" in out["firing"]
    assert not any(f.startswith("error_rate_24h") for f in out["firing"])


def test_real_success_is_still_counted_as_ok():
    rows = [_row(REAL_THESIS, status="sent"), _row(REFUSAL_TEXT, status="refused")]
    out = evaluate_lane("grok", newest_first=rows, last_24h=rows, now=NOW)
    assert out["non_error_24h"] == 1
    assert out["refused_24h"] == 1
    assert out["error_24h"] == 0


def test_real_lane_error_still_counts_as_error_and_streak():
    rows = [_row("[ERROR] read timed out", status="error")] * 5
    out = evaluate_lane("grok", newest_first=rows, last_24h=rows, now=NOW)
    assert out["error_streak"] == 5
    assert out["error_24h"] == 5
    assert out["refused_24h"] == 0
    assert "error_streak:5>=5" in out["firing"]


def test_refusal_does_not_reset_an_error_streak():
    # A refusal is neither a lane error nor a success: it is skipped, so the real errors on either
    # side of it still count. Breaking on it hid a live error streak behind model refusals (LQ-554).
    rows = [
        _row(REFUSAL_TEXT, status="refused"),
        _row("[ERROR] boom", status="error"),
        _row("[ERROR] boom", status="error"),
    ]
    assert consecutive_error_streak(rows) == 2


def test_error_refusal_error_interleaved_keeps_the_streak_and_the_error_count():
    # Newest first: error, refusal, error. The refusal must not reset the streak to 1 nor add to errors.
    rows = [
        _row("[ERROR] read timed out", status="error"),
        _row(REFUSAL_TEXT, status="refused"),
        _row("[ERROR] read timed out", status="error"),
    ]
    assert consecutive_error_streak(rows) == 2
    out = evaluate_lane("grok", newest_first=rows, last_24h=rows, now=NOW)
    assert out["error_streak"] == 2
    assert out["error_24h"] == 2
    assert out["refused_24h"] == 1
    assert out["non_error_24h"] == 0
