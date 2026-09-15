"""Market-cap size label shared by the watchlist, proposals, alerts and the CIO entry state.

Operator decision 2026-09-15: small caps are in scope for the watchlist and proposals, and every
small or micro cap is labeled as such wherever the name is shown. Bands (USD):

    NANO_CAP   < $50M
    MICRO_CAP  $50M - $300M
    SMALL_CAP  $300M - $2B
    MID_CAP    $2B - $10B
    LARGE_CAP  $10B - $200B
    MEGA_CAP   >= $200B
"""
from __future__ import annotations

from typing import Any

BANDS_MILLIONS = (
    (50.0, "NANO_CAP", "Nano cap"),
    (300.0, "MICRO_CAP", "Micro cap"),
    (2_000.0, "SMALL_CAP", "Small cap"),
    (10_000.0, "MID_CAP", "Mid cap"),
    (200_000.0, "LARGE_CAP", "Large cap"),
)
MEGA = ("MEGA_CAP", "Mega cap")
SMALL_FAMILY = {"NANO_CAP", "MICRO_CAP", "SMALL_CAP"}


def _millions(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def cap_label(market_cap_usd_millions: Any) -> dict:
    """{'code', 'text', 'is_small', 'market_cap_usd_millions'}; code UNKNOWN when cap is missing."""
    m = _millions(market_cap_usd_millions)
    if m is None:
        return {"code": "UNKNOWN", "text": "Market cap unknown", "is_small": None, "market_cap_usd_millions": None}
    for upper, code, text in BANDS_MILLIONS:
        if m < upper:
            return {"code": code, "text": text, "is_small": code in SMALL_FAMILY, "market_cap_usd_millions": round(m, 1)}
    return {"code": MEGA[0], "text": MEGA[1], "is_small": False, "market_cap_usd_millions": round(m, 1)}


def cap_label_from_usd(market_cap_usd: Any) -> dict:
    m = _millions(market_cap_usd)
    return cap_label(None if m is None else m / 1e6)


def pill(label: dict) -> str:
    """Short operator-facing text, e.g. 'Small cap · $1.4B'. Empty string when unknown."""
    m = label.get("market_cap_usd_millions")
    if m is None:
        return ""
    size = f"${m / 1000:.1f}B" if m >= 1000 else f"${m:.0f}M"
    return f"{label['text']} · {size}"
