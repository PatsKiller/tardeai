"""Shared recommendation validity for fresh input, historical caches and replay.

The existing Finviz classifier is moved unchanged. No mapping or threshold is
changed. Refused raw evidence is retained, while derived fields are unavailable.
"""

from __future__ import annotations

from typing import Any

REASON_PERCENT = "percent_sign_not_a_1_5_rating"
REASON_UNPARSEABLE = "unparseable"
REASON_OUT_OF_RANGE = "out_of_range_not_in_1_5"
REASON_SCORE_MISMATCH = "score_out_of_range_not_in_1_5"
_LEGACY_LABELS = frozenset({"strong buy", "buy", "hold", "sell", "strong sell"})


def classify_recom(recom_raw):
    """Map a Finviz recom value to (score, rating, reject_reason).

    Finviz recom is a 1-5 scale. Anything else is refused rather than coerced,
    and the caller gets a reason instead of a fabricated rating.

    This exists because the previous inline version did

        rs = float(str(recom_raw).replace("%","").strip())

    and the "%" was the one signal that the value was the WRONG FIELD. Stripping
    it laundered a percentage into a rating: when the upstream view's columns
    moved, values like "351.79%" arrived here, and 351.79 >= 4.5 rendered
    "Strong Sell".

    Measured on the live table 2026-09-13, before this change:

        last 30 days    5,774 out-of-range vs 105 valid
        since 2026-04   ~81,000 out-of-range vs ~1,800 valid
        every out-of-range row rendered "Strong Sell"

    WMT read "Strong Sell" on 351.79 while Yahoo had it at "buy" with 40
    analysts and a 137.98 mean target. Refusing is the honest outcome: no rating
    is a fact, an invented one is not.

    Returns (None, None, reason) on refusal so callers can record WHY, rather
    than being unable to distinguish "no data" from "bad data".
    """
    if recom_raw is None:
        return None, None, "missing"
    text = str(recom_raw).strip()
    if not text:
        return None, None, "empty"
    if "%" in text:
        # A percent sign means this is not a recommendation at all.
        return None, None, "percent_sign_not_a_1_5_rating"
    try:
        rs = float(text)
    except (ValueError, TypeError):
        return None, None, "unparseable"
    if not (1.0 <= rs <= 5.0):
        return None, None, f"out_of_range_{rs:g}_not_in_1_5"
    rating = (
        "Strong Buy"
        if rs < 1.5
        else "Buy"
        if rs < 2.5
        else "Hold"
        if rs < 3.5
        else "Sell"
        if rs < 4.5
        else "Strong Sell"
    )
    return round(rs, 2), rating, None


def recom_reject_reason(recom_raw: Any = None, recom_score: Any = None) -> str | None:
    """Return a refusal, or None for valid evidence / an absent observation.

    Historical named labels require valid numeric evidence. They cannot create
    a numeric score. Both fields are validated by the original classifier.
    """
    raw_score = score = None
    legacy_label = None
    if recom_raw is not None:
        raw_score, _, reason = classify_recom(recom_raw)
        if reason is not None:
            label = str(recom_raw).strip().lower()
            if label not in _LEGACY_LABELS or recom_score is None:
                return REASON_OUT_OF_RANGE if reason.startswith("out_of_range_") else reason
            legacy_label = label
    if recom_score is not None:
        score, rating, reason = classify_recom(recom_score)
        if reason is not None:
            return REASON_SCORE_MISMATCH if reason.startswith("out_of_range_") else reason
        if legacy_label is not None and legacy_label != rating.lower():
            return "raw_label_score_mismatch"
    if raw_score is not None and score is not None and raw_score != score:
        return "score_mismatch_with_raw"
    return None


def is_valid_recom(recom_raw: Any = None, recom_score: Any = None) -> bool:
    """True only when numeric evidence exists and no field is refused."""
    if recom_reject_reason(recom_raw, recom_score) is not None:
        return False
    return any(classify_recom(value)[2] is None for value in (recom_raw, recom_score) if value is not None)


def sanitize_enrichment_record(record: dict) -> str | None:
    """Clear refused derived fields in memory; preserve raw/provenance bytes."""
    reason = recom_reject_reason(record.get("recom"), record.get("recom_score"))
    if reason is None and record.get("analyst_rating") is not None and not isinstance(record["analyst_rating"], str):
        reason = "analyst_rating_invalid"
    if reason is None and record.get("analyst_rating"):
        numeric = record.get("recom_score")
        if numeric is None:
            numeric = record.get("recom")
        _, expected_rating, _ = classify_recom(numeric)
        if expected_rating is not None and str(record["analyst_rating"]).strip().lower() != expected_rating.lower():
            reason = "analyst_rating_score_mismatch"
    if (
        reason is None
        and record.get("analyst_rating")
        and not is_valid_recom(record.get("recom"), record.get("recom_score"))
    ):
        reason = "missing_numeric_evidence"
    if reason is not None:
        record["recom_score"] = None
        record["analyst_rating"] = None
        record["recom_reject_reason"] = reason
    return reason
