"""Model-classified path for segment lines the deterministic table cannot place (DSN-20261101 §3.2) — P1 STUB.

:func:`classify` never calls a model: it imports no model client and returns ``status: not_built``. The P3 build will
route it through the governed model-job path (OAuth-first, cost-capped process ``issuer_segment_classifier``).

:func:`accept` is the deterministic gate the writer will apply to any model output, built and tested now so P3 cannot
weaken it: ``group`` must be a sector key, ``quote`` must be a verbatim substring of the filing text (after whitespace
normalisation), ``confidence`` must reach the floor, and a ``theme_suggestion`` is kept for display only, never applied.
"""
from __future__ import annotations

import re
from typing import Any

NOT_BUILT = "not_built"


def classify(item: dict[str, Any], filing_text: str = "", *, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stub. Returns the line unclassified; the caller keeps the profile-sector fallback and its visible flag."""
    return {"status": NOT_BUILT, "member": item.get("member"), "label": item.get("label"), "model_called": False,
            "group": None, "confidence": None, "flag": "segment_unmapped_fallback"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def accept(output: dict[str, Any], filing_text: str, *, sector_keys: list[str], min_confidence: float) -> dict[str, Any]:
    """Accept or reject one model output. Returns ``{accepted, reason, group, confidence, theme_suggestion}``."""
    group = output.get("group")
    quote = _norm(str(output.get("quote") or ""))
    try:
        conf = float(output.get("confidence"))
    except (TypeError, ValueError):
        conf = -1.0
    reason = None
    if group not in set(sector_keys):
        reason = "group_not_a_sector_key"
    elif not quote or quote not in _norm(filing_text):
        reason = "quote_not_in_filing"
    elif not (0.0 <= conf <= 1.0) or conf < float(min_confidence):
        reason = "below_confidence_floor"
    ok = reason is None
    return {"accepted": ok, "reason": reason, "group": group if ok else None, "confidence": conf if ok else None,
            "basis": "model_classified" if ok else "profile_fallback",
            "flag": None if ok else "segment_unmapped_fallback",
            "theme_suggestion": output.get("theme_suggestion"), "theme_applied": False}
