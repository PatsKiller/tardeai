"""Indicator -> signal normalization (§2.1). Every input is a plain series; every constant comes from the policy.

A function here returns ``(signal, detail)`` where ``signal`` is in [-1, +1] (+ = supportive of risk) or ``None`` when
the input cannot support a measurement, and ``detail`` is the one-line audit text the brief and the record carry.
None ALWAYS means "not measured"; nothing here substitutes a zero for missing data (§2.2, §2.9).
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Sequence


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def sma(values: Sequence[float], n: int) -> float | None:
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def _closes(bars: Sequence[dict[str, Any]]) -> list[float]:
    return [float(b["close"]) for b in bars]


# ── level series: trend state (§2.1 first bullet) ──────────────────────────────────────────────────────────────
def trend_state(bars: Sequence[dict[str, Any]], cfg: dict[str, Any]) -> tuple[float | None, str]:
    c = _closes(bars)
    need = int(cfg["min_bars"])
    if len(c) < need:
        return None, f"only {len(c)} daily bars, needs {need}"
    w = cfg["weights"]
    mid = int(cfg["close_vs_sma_sessions"])
    long = int(cfg["close_vs_long_sma_sessions"])
    slope_n = int(cfg["slope_sma_sessions"])
    window = int(cfg["slope_window_sessions"])
    s50, s200 = sma(c, mid), sma(c, long)
    now20 = sma(c, slope_n)
    prev20 = sma(c[:-window], slope_n)
    now50 = sma(c, mid)
    prev50 = sma(c[:-window], mid)
    if s50 is None or s200 is None or now20 is None or prev20 is None or now50 is None or prev50 is None:
        return None, "not enough history for the 20/50/200 averages"
    parts = {
        "close_vs_sma": sign(c[-1] - s50),
        "slope_sma": sign(now20 - prev20),
        "close_vs_long_sma": sign(c[-1] - s200),
    }
    s = sum(float(w[k]) * parts[k] for k in parts)
    falling20, falling50 = now20 < prev20, now50 < prev50
    penalised = now20 < now50 and falling20 and falling50
    if penalised:
        s *= 1.0 - float(cfg["downtrend_penalty"])
    detail = (
        f"close {c[-1]:.2f} vs 50DMA {s50:.2f} ({'above' if parts['close_vs_sma'] > 0 else 'below'}), "
        f"20DMA {'rising' if parts['slope_sma'] > 0 else 'falling'}, "
        f"vs 200DMA {s200:.2f} ({'above' if parts['close_vs_long_sma'] > 0 else 'below'})"
        + (", confirmed downtrend" if penalised else "")
    )
    return clip(s), detail


def weekly_state(bars: Sequence[dict[str, Any]], cfg: dict[str, Any]) -> tuple[float | None, str]:
    """5-session return standardised by 5-session realized vol, clipped +-clip then /2 (weekly change, §2.1)."""
    c = _closes(bars)
    ret_n = int(cfg["return_sessions"])
    rv_n = int(cfg["rv_sessions"])
    if len(c) < max(int(cfg["min_bars"]), ret_n + 2, rv_n + 2):
        return None, f"only {len(c)} daily bars, needs {max(int(cfg['min_bars']), rv_n + 2)}"
    ret = c[-1] / c[-1 - ret_n] - 1.0
    daily = [c[i] / c[i - 1] - 1.0 for i in range(len(c) - rv_n, len(c))]
    sd = statistics.pstdev(daily)
    if sd <= 0:
        return None, "zero realized volatility over the window"
    z = ret / (sd * math.sqrt(ret_n))  # a 5-session return in 5-session-vol units
    s = clip(z, -float(cfg["clip"]), float(cfg["clip"])) / 2.0
    return s, f"5-session return {ret * 100:+.2f}% = {z:+.2f} sigma"


# ── ratio / spread series: z-score (§2.1 second bullet) ────────────────────────────────────────────────────────
def z_state(values: Sequence[float], cfg: dict[str, Any], *, invert: bool = False) -> tuple[float | None, str]:
    need = int(cfg["min_history_sessions"])
    if len(values) < need:
        return None, f"only {len(values)} observations, needs {need}"
    window = values[-min(int(cfg["window_sessions"]), len(values)) :]
    if len(window) < need:
        return None, f"only {len(window)} observations in the window, needs {need}"
    mean = sum(window) / len(window)
    sd = statistics.pstdev(window)
    if sd <= 0:
        return None, "zero dispersion over the window"
    raw = (window[-1] - mean) / sd
    s = clip(raw, -float(cfg["clip"]), float(cfg["clip"])) / float(cfg["scale"])
    if invert:
        s = -s
    return s, f"z {raw:+.2f} over {len(window)} obs (mean {mean:.4g}, sd {sd:.4g})"


# ── vol levels: percentile (§2.1 third bullet) ────────────────────────────────────────────────────────────────
def percentile_state(values: Sequence[float], cfg: dict[str, Any]) -> tuple[float | None, float | None, str]:
    """``(signal, percentile, detail)``; signal = 1 - 2*pct so a high vol percentile is risk-negative."""
    need = int(cfg["min_observations"])
    if len(values) < need:
        return None, None, f"only {len(values)} observations, needs {need}"
    last = values[-1]
    pct = sum(1 for v in values if v <= last) / len(values)
    s = clip(1.0 - 2.0 * pct, -1.0, 1.0)
    return s, pct, f"{last:.4g} at the {pct * 100:.0f}th percentile of {len(values)} obs"


def term_structure_state(
    vix: float | None, vix9d: float | None, vix3m: float | None, veto: str | None, cfg: dict[str, Any]
) -> tuple[float | None, str]:
    """VIX term structure override (§2.1): full inversion caps the signal at -0.6; calm contango at +0.6."""
    if veto:
        return None, veto
    if vix is None or vix9d is None or vix3m is None:
        return None, "VIX9D / VIX / VIX3M not all readable from a clean feed"
    if vix9d > vix > vix3m:
        return float(cfg["term_full_inversion_cap"]), f"full inversion VIX9D {vix9d:.2f} > VIX {vix:.2f} > VIX3M {vix3m:.2f}"
    if vix < float(cfg["complacency_vix"]) and vix < vix3m:
        return float(cfg["contango_complacency_cap"]), f"contango with VIX {vix:.2f} < {cfg['complacency_vix']}"
    ratio = vix / vix3m
    s = clip((1.0 - ratio) * 5.0)  # steeper contango (ratio < 1) is mildly supportive, backwardation negative
    return s, f"VIX / VIX3M {ratio:.3f}"


# ── breadth (§2.1 fourth bullet) ───────────────────────────────────────────────────────────────────────────────
def breadth_pct_state(pct: float, cfg: dict[str, Any]) -> tuple[float, str]:
    s = clip((pct - float(cfg["pct_above_center"])) / float(cfg["pct_above_scale"]))
    return s, f"{pct:.1f}% above"


def high_low_state(highs: int, lows: int, cfg: dict[str, Any]) -> tuple[float | None, str]:
    total = int(highs) + int(lows)
    if total <= 0:
        return None, "no new-high / new-low rows in the batch"
    ratio = (int(highs) - int(lows)) / total
    s = clip(ratio / float(cfg["high_low_divisor"]))
    return s, f"{int(highs)} new highs vs {int(lows)} new lows ({ratio * 100:+.1f}%)"


def mcclellan_state(breadth_pcts: Sequence[float], cfg: dict[str, Any]) -> tuple[float | None, str]:
    vals = [float(v) for v in breadth_pcts if v is not None]
    if not vals:
        return None, "no sector breadth readings"
    mean = sum(vals) / len(vals)
    s = clip((mean - float(cfg["pct_above_center"])) / float(cfg["mcclellan_divisor"]))
    return s, f"mean SPDR breadth {mean:.1f}% over {len(vals)} sectors"


# ── positioning (§2.1 fifth bullet) ────────────────────────────────────────────────────────────────────────────
def positioning_state(
    ratio: float, history: Sequence[float], vix_pct: float | None, cfg: dict[str, Any]
) -> tuple[float | None, str, bool]:
    """``(signal, detail, contrarian)`` — contrarian flip at an extreme put/call with a high VIX percentile."""
    need = int(cfg["min_history_sessions"])
    if len(history) < need:
        return None, f"only {len(history)} put/call observations, needs {need}", False
    window = history[-min(int(cfg["median_sessions"]), len(history)) :]
    median = statistics.median(window)
    if median <= 0:
        return None, "put/call median is zero", False
    multiple = ratio / median
    if multiple > float(cfg["contrarian_ratio"]) and vix_pct is not None and vix_pct > float(
        cfg["contrarian_vix_percentile"]
    ):
        return (
            float(cfg["contrarian_score"]),
            f"P/C {ratio:.2f} = {multiple:.2f}x median with VIX at the {vix_pct * 100:.0f}th pct: capitulation (contrarian)",
            True,
        )
    s = -clip((multiple - 1.0) / float(cfg["ratio_scale"]))
    return s, f"P/C {ratio:.2f} = {multiple:.2f}x median over {len(window)} obs", False


def mover_skew_state(gainers_mean: float | None, losers_mean: float | None, cfg: dict[str, Any]) -> tuple[float | None, str]:
    if gainers_mean is None or losers_mean is None:
        return None, "movers batch has no gainers/losers mean"
    skew = float(gainers_mean) + float(losers_mean)  # losers_mean is negative
    s = clip(skew / float(cfg["mover_skew_scale"]))
    return s, f"mean gainer {gainers_mean:+.1f}% + mean loser {losers_mean:+.1f}% = {skew:+.1f} pts"


# ── rates / dollar (§2.1 sixth bullet) ────────────────────────────────────────────────────────────────────────
def rates_bp_state(values: Sequence[float], cfg: dict[str, Any]) -> tuple[float | None, str]:
    n = int(cfg["change_sessions"])
    if len(values) < n + 1:
        return None, f"only {len(values)} yield observations, needs {n + 1}"
    delta_bp = (values[-1] - values[-1 - n]) * 100.0
    s = -clip(delta_bp / float(cfg["bp_scale"]))
    return s, f"{delta_bp:+.1f} bp over {n} sessions"


def dollar_pct_state(values: Sequence[float], cfg: dict[str, Any]) -> tuple[float | None, str]:
    n = int(cfg["change_sessions"])
    if len(values) < n + 1 or values[-1 - n] == 0:
        return None, f"only {len(values)} dollar observations, needs {n + 1}"
    delta_pct = (values[-1] / values[-1 - n] - 1.0) * 100.0
    s = -clip(delta_pct / float(cfg["pct_scale"]))
    return s, f"{delta_pct:+.2f}% over {n} sessions"


def event_tilt_state(tilt: float, cfg: dict[str, Any]) -> tuple[float, str]:
    """``tilt`` is tau already scaled by ``impact_levels`` (§2.6: tau = -tilt_per_impact * max impact, e.g. -0.15
    for a HIGH catalyst) and IS the category-10 signal. Pass it through un-rescaled: dividing by
    ``tilt_per_impact`` turned tau=-0.15 into a full -1.00 and overstated the S penalty by ~7 points
    (§2.10 worked example: CPI HIGH -> tau -0.15 -> C10 ~ -0.15; LQ-985 review finding 1)."""
    return clip(float(tilt), -1.0, 0.0), f"tilt {tilt:+.2f} into the next {cfg['tilt_sessions']} sessions"


__all__ = [
    "clip",
    "sign",
    "sma",
    "trend_state",
    "weekly_state",
    "z_state",
    "percentile_state",
    "term_structure_state",
    "breadth_pct_state",
    "high_low_state",
    "mcclellan_state",
    "positioning_state",
    "mover_skew_state",
    "rates_bp_state",
    "dollar_pct_state",
    "event_tilt_state",
]
