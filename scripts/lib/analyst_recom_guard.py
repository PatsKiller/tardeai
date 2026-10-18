"""One guard for Finviz "Recom" analyst-consensus values (2026-10-18).

Finviz "Recom" is a 1.0 (Strong Buy) .. 5.0 (Strong Sell) mean. Before the
2026-09-13 header-keyed parse, a positional map stored "Performance (10 Years)"
in the ``recom`` field, so values like ``"-95.44%"`` (JNUG) and ``"938.86%"``
(BELFB) became ``recom_score`` -95.44 / 938.86 and rendered "Strong Buy" /
"Strong Sell" -- inverted, and anti-correlated with reality.

The parse was fixed, but stale ``ticker_enrichment_cache.json`` entries written
before the fix are never refreshed for symbols that left the active universe,
and ``save_analyst_consensus_history`` replayed them into
``analyst_consensus_history`` every day since 2026-09-08. Consumer guards were
also leaky: a raw ``"3.81%"`` parses to 3.81 and passes a bare 1..5 check.

Every writer, loader and reader of a Finviz recom value goes through
``recom_reject_reason``. A non-None reason means: do not store, do not render,
and count the refusal.
"""
from __future__ import annotations

import math
from typing import Any

RECOM_MIN = 1.0
RECOM_MAX = 5.0

REASON_PERCENT = "percent_sign_not_a_1_5_rating"
REASON_UNPARSEABLE = "unparseable"
REASON_OUT_OF_RANGE = "out_of_range_not_in_1_5"
REASON_SCORE_MISMATCH = "score_out_of_range_not_in_1_5"


def _as_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def recom_reject_reason(recom_raw: Any = None, recom_score: Any = None) -> str | None:
    """Return why a (raw, score) pair is NOT a 1..5 analyst recommendation, else None.

    ``None`` for both is "no data", not bad data, and returns None.
    """
    if recom_raw is not None:
        text = str(recom_raw).strip()
        if "%" in text:
            return REASON_PERCENT
        if text and text != "-":
            raw_f = _as_float(text)
            # A non-numeric raw is a label (the hermes lane stores "buy");
            # it is judged by its score below. A numeric raw must be 1..5.
            if raw_f is not None and not (RECOM_MIN <= raw_f <= RECOM_MAX):
                return REASON_OUT_OF_RANGE
    if recom_score is not None:
        score_f = _as_float(recom_score)
        if score_f is None:
            return REASON_UNPARSEABLE
        if not (RECOM_MIN <= score_f <= RECOM_MAX):
            return REASON_SCORE_MISMATCH
    return None


def is_valid_recom(recom_raw: Any = None, recom_score: Any = None) -> bool:
    """True only when a real 1..5 score is present and nothing refuses it."""
    if recom_reject_reason(recom_raw, recom_score) is not None:
        return False
    return _as_float(recom_score) is not None or _as_float(recom_raw) is not None


def sanitize_enrichment_record(record: dict) -> str | None:
    """Null the derived analyst fields of a cache record whose recom is refused.

    Mutates ``record`` in place: ``recom_score`` and ``analyst_rating`` become
    None and ``recom_reject_reason`` names why. ``recom`` (the raw text) is kept
    as evidence. Returns the reason, or None when the record is clean.
    """
    if not isinstance(record, dict):
        return None
    reason = recom_reject_reason(record.get("recom"), record.get("recom_score"))
    if reason is None:
        return None
    record["recom_score"] = None
    record["analyst_rating"] = None
    record["recom_reject_reason"] = reason
    return reason
