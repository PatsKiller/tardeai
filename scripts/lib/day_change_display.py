"""Render a day change so "unknown" is a word, never a zero.

A missing day change is not a flat day.  The store now carries ``None`` for a row whose day
change could not be measured (a Fidelity statement row with no previous close, a NAV mark
with no preceding NAV, a CSV import that has no day-change column).  Formatting that ``None``
with ``:+,.0f`` raised ``TypeError`` and took the whole LLM portfolio context with it
(codex-cloud P2 on PR #2588); coercing it with ``or 0`` told the operator the book was flat.

Every surface renders through these helpers.  A genuinely measured ``0.00`` is still a
number and still renders as zero — the positive control against over-tightening.
"""
from __future__ import annotations

import math

UNKNOWN = "unknown"


def is_measured(value) -> bool:
    """True only for a finite int/float that is not a bool.

    Strings are deliberately NOT coerced.  ``"0"`` from a corrupted document is not
    evidence that a day change was measured, and inventing a float from it is the
    failure mode this module exists to stop.
    """
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def format_amount(value, *, currency: str = "$", signed: bool = False,
                  places: int = 0, unknown: str = UNKNOWN) -> str:
    """``$1,234`` / ``$-12`` / ``unknown``; a measured 0 renders as ``$0``."""
    if not is_measured(value):
        return unknown
    v = float(value)
    if v == 0.0:
        v = 0.0  # normalize -0.0 so a measured zero never renders as "-0"
    if places <= 0:
        body = f"{v:+,.0f}" if signed else f"{v:,.0f}"
    else:
        body = f"{v:+.{places}f}" if signed else f"{v:.{places}f}"
    return f"{currency}{body}"


def format_pct(value, *, places: int = 1, signed: bool = False,
               unknown: str = UNKNOWN) -> str:
    """``1.0%`` / ``+1.0%`` / ``unknown``; a measured 0 renders as ``0.0%``."""
    if not is_measured(value):
        return unknown
    v = float(value)
    if v == 0.0:
        v = 0.0
    body = f"{v:+.{places}f}" if signed else f"{v:.{places}f}"
    return f"{body}%"


def format_day_change(value, *, currency: str = "$", signed: bool = True,
                      places: int = 0, unknown: str = UNKNOWN) -> str:
    """``$+1,234`` / ``$-12`` / ``unknown``; a measured 0 renders as ``$+0``."""
    return format_amount(value, currency=currency, signed=signed, places=places,
                         unknown=unknown)


def format_day_change_pct(value, *, places: int = 2, signed: bool = True,
                          unknown: str = UNKNOWN) -> str:
    """``+1.23%`` / ``-0.50%`` / ``unknown``; a measured 0 renders as ``+0.00%``."""
    return format_pct(value, places=places, signed=signed, unknown=unknown)
