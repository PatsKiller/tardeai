"""Canonical Finviz recom (1-5) → text label mapping.

Finviz 'recom' is NOT the same as Street analyst consensus; this helper is
shared so enrichment paths stay consistent. UI surfaces that need Yahoo/Hermes
consensus should use build_pro_analyst_read_model / pro_analyst_pills_latest.json.
"""
from __future__ import annotations

from typing import Any


def finviz_recom_to_label(recom: Any) -> str | None:
    if recom is None:
        return None
    try:
        rs = float(str(recom).replace("%", "").strip())
    except (ValueError, TypeError):
        return None
    if rs < 1.5:
        return "Strong Buy"
    if rs < 2.5:
        return "Buy"
    if rs < 3.5:
        return "Hold"
    if rs < 4.5:
        return "Sell"
    return "Strong Sell"


def apply_finviz_analyst_fields(merged: dict[str, Any], recom_raw: Any) -> None:
    """Set recom_score + analyst_rating on an enrichment dict (in-place)."""
    if recom_raw is None:
        return
    try:
        rs = float(str(recom_raw).replace("%", "").strip())
        merged["recom_score"] = round(rs, 2)
        merged["analyst_rating"] = finviz_recom_to_label(rs)
    except (ValueError, TypeError):
        merged["recom_score"] = None
        merged["analyst_rating"] = None
