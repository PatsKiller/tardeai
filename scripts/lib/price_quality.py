"""Detect historically-corrupt rows in a ticker price series.

Audit finding C3, Stage B. Stage A (PR #524) added an ingestion guard that
compares each incoming price to the prior close, which stops *new* corruption.
It cannot find what is already stored, and the prior-close comparison has a
blind spot this module exists to close.

**Why not compare to neighbours.** The known-bad case is NVDA 2026-05-04..06,
where three consecutive rows read 0.66, 0.18, 0.05 between closes near $200.
Adjacent-row comparison misses it: each corrupt row's neighbour is *also*
corrupt, so the step between them is small and nothing trips a 10x rule. A run
of corruption hides itself. Only 05-04 and 05-06 look unusual against one side,
and neither passes a both-sides test.

So the baseline here is the **median of a window around the row, excluding the
row itself and its immediate neighbours**. A median is unmoved by a minority of
corrupt samples, and skipping the adjacent rows keeps a short run from
contaminating its own baseline. NVDA's three rows are then each ~3000x below a
~$200 baseline and all three are caught.

**Splits are deliberately not flagged.** A 1:10 split is a real 10x step that
*persists*: the window median moves with it, and prices after the step sit near
the new baseline. Corruption reverts. Rows are therefore only flagged when they
deviate from a baseline that the surrounding data does not support, which a
split does not produce. `classify_series` reports `step_like` separately so a
caller can see splits were considered rather than silently ignored.

AUTHORITY: READ_ONLY_ADVISORY. Pure functions, no DB, no I/O. Detection only —
deciding what to do about a flagged row belongs to the caller.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Iterable, NamedTuple, Sequence

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "PriceQualityFinding@v1"

# A row must sit this far from its window baseline to be called corrupt. Matches
# the audit's own 10x outlier definition, so this finds what the audit counted.
DEFAULT_DEVIATION = 10.0
# Window half-width in rows. 5 each side gives a 10-sample baseline, enough for a
# stable median while staying local enough to track a genuinely trending price.
DEFAULT_HALF_WINDOW = 5
# Immediate neighbours are excluded: a corrupt run must not form its own baseline.
DEFAULT_GUARD = 1
# Below this many usable baseline samples, decline to judge rather than guess.
MIN_BASELINE_SAMPLES = 4

REASON_NAN = "non_finite"
REASON_NON_POSITIVE = "non_positive"
REASON_DEVIATION = "window_median_deviation"


class PriceFinding(NamedTuple):
    index: int
    date: Any
    price: float | None
    baseline: float | None
    ratio: float | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "date": str(self.date),
            "price": self.price,
            "baseline": self.baseline,
            "ratio": self.ratio,
            "reason": self.reason,
            "schema": SCHEMA,
        }


def _as_float(value: Any) -> float | None:
    """None for anything not a usable finite number (NaN, Inf, junk)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _side_median(prices: Sequence[float | None], lo: int, hi: int) -> float | None:
    sample = [p for j in range(lo, hi) if (p := prices[j]) is not None and p > 0]
    if len(sample) < MIN_BASELINE_SAMPLES:
        return None
    return median(sample)


def _baselines(
    prices: Sequence[float | None], i: int, half_window: int, guard: int
) -> tuple[float | None, float | None]:
    """Medians of the left and right windows, each excluding i and its guard band.

    Kept as two independent values on purpose. A single median over the whole
    window cannot tell a reverting spike from a persistent step: at a 1:10
    reverse split the window straddles two regimes, the median lands in one of
    them, and every row on the other side reads as a 10x outlier. That flags both
    sides of a legitimate split -- which an earlier version of this module did,
    on SRNE (0.0008 -> 0.2954, sustained).
    """
    left = _side_median(prices, max(0, i - half_window), max(0, i - guard))
    right = _side_median(prices, min(len(prices), i + guard + 1), min(len(prices), i + half_window + 1))
    return left, right


def find_corrupt_rows(
    rows: Iterable[tuple[Any, Any]],
    *,
    deviation: float = DEFAULT_DEVIATION,
    half_window: int = DEFAULT_HALF_WINDOW,
    guard: int = DEFAULT_GUARD,
) -> list[PriceFinding]:
    """Corrupt rows in one symbol's series. `rows` = (date, price), date-ascending.

    Non-finite and non-positive prices are always corrupt -- no baseline needed,
    a price cannot be NaN or zero. Everything else is judged against the window
    median, and a row with too little surrounding data is left alone.
    """
    seq = list(rows)
    prices = [_as_float(p) for _, p in seq]
    out: list[PriceFinding] = []

    for i, (dt, raw) in enumerate(seq):
        price = prices[i]
        if price is None:
            out.append(PriceFinding(i, dt, None, None, None, REASON_NAN))
            continue
        if price <= 0:
            out.append(PriceFinding(i, dt, price, None, None, REASON_NON_POSITIVE))
            continue

        left, right = _baselines(prices, i, half_window, guard)
        # Both sides must exist and both must disagree with the row. A row at a
        # split boundary matches whichever regime it belongs to, so it fails this
        # test and is left alone. A reverting spike matches neither.
        if not left or not right or left <= 0 or right <= 0:
            continue
        r_left = price / left if price >= left else left / price
        r_right = price / right if price >= right else right / price
        if r_left < deviation or r_right < deviation:
            continue
        base = min(left, right, key=lambda b: abs(math.log(price / b)))
        out.append(PriceFinding(i, dt, price, base, round(min(r_left, r_right), 2), REASON_DEVIATION))

    return out


def classify_series(
    rows: Iterable[tuple[Any, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Findings plus the step-like count, so splits are visibly considered.

    A step is a large adjacent move where the level afterwards holds -- a split
    or a genuine repricing. It is reported, never flagged.
    """
    seq = list(rows)
    findings = find_corrupt_rows(seq, **kwargs)
    flagged = {f.index for f in findings}
    prices = [_as_float(p) for _, p in seq]

    step_like = 0
    for i in range(1, len(prices)):
        if i in flagged:
            continue
        prev, cur = prices[i - 1], prices[i]
        if not prev or not cur or prev <= 0 or cur <= 0:
            continue
        jump = cur / prev if cur >= prev else prev / cur
        if jump < DEFAULT_DEVIATION:
            continue
        after = [p for p in prices[i + 1:i + 4] if p and p > 0]
        if after and median(after) / cur < DEFAULT_DEVIATION and cur / median(after) < DEFAULT_DEVIATION:
            step_like += 1

    return {
        "rows": len(seq),
        "findings": [f.as_dict() for f in findings],
        "corrupt_rows": len(findings),
        "step_like_rows": step_like,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }
