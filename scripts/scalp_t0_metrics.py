#!/usr/bin/env python3
"""M3-S2 — Tier-0 (bars-only) microstructure metric library (Momentum Scalp Signal Engine).

Pure functions over a bar series. No I/O, no DB, no network, no order/proposal path. These are the
T0 substitutes on the §4.3 fallback ladder — every one is computable from OHLCV bars alone, so Lane A
never hard-depends on Level 2 or moomoo. Implemented here, consumed by the M3-S3 ignition scorer.

Metrics (design doc §4.3):
  - bar_pressure         — volume-weighted close location (Chaikin lineage), ∈ [−1, +1];
                           same sign convention as TFI/BI (T0 directional-pressure substitute).
  - corwin_schultz_spread — high-low spread estimator (Corwin & Schultz 2012), proportional.
  - abdi_ranaldo_spread   — close/high/low spread estimator (Abdi & Ranaldo 2017), proportional.
  - spread_estimate       — max(CS, AR): the conservative T0 transaction-cost estimate.
  - amihud_illiq          — Amihud (2002) illiquidity = mean(|r| / dollar-volume).
  - effort_vs_result      — Wyckoff EvR = (|ΔP|/ATR) / (V/μ_V): low on high volume = absorption.

NOTE (design §4.3): the Roll (1984) estimator is deliberately NOT implemented — momentum ignition
produces positively autocorrelated returns, the regime where Roll is undefined/nonsense.

A "bar" is a mapping with open/high/low/close/volume. Both short (o/h/l/c/v) and long
(open/high/low/close/volume) key styles are accepted; Alpaca raw bars (t/o/h/l/c/v) work directly.
"""
from __future__ import annotations

import math
import statistics
from typing import Mapping, Sequence

Bar = Mapping[str, float]

_ROOT_CONST = 3.0 - 2.0 * math.sqrt(2.0)  # Corwin-Schultz denominator constant ≈ 0.1715729


# ─────────────────────────── accessors ───────────────────────────

def _g(bar: Bar, *keys: str) -> float | None:
    for k in keys:
        if k in bar and bar[k] is not None:
            try:
                return float(bar[k])
            except (TypeError, ValueError):
                return None
    return None


def _o(b: Bar): return _g(b, "o", "open", "O")
def _h(b: Bar): return _g(b, "h", "high", "H")
def _l(b: Bar): return _g(b, "l", "low", "L")
def _c(b: Bar): return _g(b, "c", "close", "C")
def _v(b: Bar): return _g(b, "v", "volume", "V")


# ─────────────────────────── directional pressure (T0) ───────────────────────────

def clv(bar: Bar) -> float | None:
    """Close Location Value = (C − L) / (H − L) ∈ [0, 1]. None when H == L (undefined)."""
    h, l, c = _h(bar), _l(bar), _c(bar)
    if h is None or l is None or c is None or h <= l:
        return None
    return (c - l) / (h - l)


def bar_pressure(bars: Sequence[Bar]) -> float | None:
    """Volume-weighted close location, mapped to [−1, +1]:
        BarPressure = Σ (2·CLV_i − 1)·V_i / Σ V_i
    +1 = every bar closed on its high on volume; −1 = on its low. Bars with H==L or missing
    volume are skipped. Returns None if no usable volume."""
    num = 0.0
    den = 0.0
    for b in bars:
        cv = clv(b)
        v = _v(b)
        if cv is None or v is None or v <= 0:
            continue
        num += (2.0 * cv - 1.0) * v
        den += v
    if den <= 0:
        return None
    return num / den


# ─────────────────────────── transaction cost (T0) ───────────────────────────

def corwin_schultz_spread(bars: Sequence[Bar]) -> float | None:
    """Corwin–Schultz (2012) proportional spread, averaged over consecutive bar pairs.
    Per-pair negative estimates clamp to 0 before averaging (design §4.3)."""
    est: list[float] = []
    for t in range(len(bars) - 1):
        b0, b1 = bars[t], bars[t + 1]
        h0, l0, h1, l1 = _h(b0), _l(b0), _h(b1), _l(b1)
        if None in (h0, l0, h1, l1) or l0 <= 0 or l1 <= 0 or h0 <= 0 or h1 <= 0:
            continue
        beta = math.log(h0 / l0) ** 2 + math.log(h1 / l1) ** 2
        hmax, lmin = max(h0, h1), min(l0, l1)
        if lmin <= 0:
            continue
        gamma = math.log(hmax / lmin) ** 2
        alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / _ROOT_CONST - math.sqrt(gamma / _ROOT_CONST)
        s = 2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha))
        est.append(max(s, 0.0))
    if not est:
        return None
    return statistics.mean(est)


def abdi_ranaldo_spread(bars: Sequence[Bar]) -> float | None:
    """Abdi–Ranaldo (2017) proportional spread from close/high/low.
        η_t = (ln H_t + ln L_t)/2 ;  c_t = ln C_t
        S = 2·√( max(0, mean_t[ (c_t − η_t)(c_t − η_{t+1}) ]) )
    Generally more accurate than CS on high-volatility names."""
    c: list[float] = []
    eta: list[float] = []
    for b in bars:
        h, l, cl = _h(b), _l(b), _c(b)
        if None in (h, l, cl) or h <= 0 or l <= 0 or cl <= 0:
            c.append(math.nan)
            eta.append(math.nan)
            continue
        c.append(math.log(cl))
        eta.append((math.log(h) + math.log(l)) / 2.0)
    terms: list[float] = []
    for t in range(len(c) - 1):
        if any(math.isnan(x) for x in (c[t], eta[t], eta[t + 1])):
            continue
        terms.append((c[t] - eta[t]) * (c[t] - eta[t + 1]))
    if not terms:
        return None
    return 2.0 * math.sqrt(max(0.0, statistics.mean(terms)))


def spread_estimate(bars: Sequence[Bar]) -> float | None:
    """Conservative T0 spread = max(Corwin–Schultz, Abdi–Ranaldo) (design §4.3)."""
    cs = corwin_schultz_spread(bars)
    ar = abdi_ranaldo_spread(bars)
    vals = [x for x in (cs, ar) if x is not None]
    return max(vals) if vals else None


# ─────────────────────────── impact / illiquidity (T0) ───────────────────────────

def amihud_illiq(bars: Sequence[Bar]) -> float | None:
    """Amihud (2002) illiquidity = mean( |r_bar| / dollar_volume_bar ), r from close-to-close.
    Raw (unscaled) units; callers may scale by 1e6 for readability. Larger = more illiquid."""
    ratios: list[float] = []
    prev_c = None
    for b in bars:
        cl, v = _c(b), _v(b)
        if cl is None or cl <= 0 or v is None or v <= 0:
            prev_c = cl if (cl and cl > 0) else prev_c
            continue
        if prev_c is not None and prev_c > 0:
            r = abs(cl - prev_c) / prev_c
            dollar_vol = cl * v
            if dollar_vol > 0:
                ratios.append(r / dollar_vol)
        prev_c = cl
    if not ratios:
        return None
    return statistics.mean(ratios)


# ─────────────────────────── absorption / effort-vs-result (T0) ───────────────────────────

def evr_bar(delta_p: float, atr: float, v_bar: float, vol_ma: float) -> float | None:
    """Wyckoff effort-vs-result for one bar:
        EvR = (|ΔP| / ATR) / (V / μ_V)
    Low EvR = large effort (volume) with little result (price) = supply absorbing demand.
    None if ATR or μ_V or effort is non-positive (undefined)."""
    if atr is None or atr <= 0 or vol_ma is None or vol_ma <= 0 or v_bar is None or v_bar <= 0:
        return None
    effort = v_bar / vol_ma
    if effort <= 0:
        return None
    result = abs(delta_p) / atr
    return result / effort


def true_range(bar: Bar, prev_close: float | None) -> float | None:
    h, l, c = _h(bar), _l(bar), _c(bar)
    if h is None or l is None:
        return None
    rng = h - l
    if prev_close is not None:
        rng = max(rng, abs(h - prev_close), abs(l - prev_close))
    return rng


def atr(bars: Sequence[Bar], period: int = 14) -> float | None:
    """Simple average true range over the last `period` bars (SMA of TR). Pure."""
    trs: list[float] = []
    prev_c = None
    for b in bars:
        tr = true_range(b, prev_c)
        if tr is not None:
            trs.append(tr)
        prev_c = _c(b) if _c(b) is not None else prev_c
    if len(trs) < 1:
        return None
    window = trs[-period:] if period > 0 else trs
    return statistics.mean(window)


def volume_ma(bars: Sequence[Bar], period: int = 20) -> float | None:
    vols = [_v(b) for b in bars if _v(b) is not None]
    if not vols:
        return None
    window = vols[-period:] if period > 0 else vols
    return statistics.mean(window)


def effort_vs_result(bars: Sequence[Bar], atr_period: int = 14, vol_period: int = 20) -> list[float | None]:
    """Per-bar EvR series. For each bar i, ΔP = |close_i − open_i| (bar body / net result),
    ATR and μ_V computed from the trailing window up to (and including) bar i. Pure."""
    out: list[float | None] = []
    for i in range(len(bars)):
        window = bars[: i + 1]
        a = atr(window, atr_period)
        vma = volume_ma(window, vol_period)
        o, c, v = _o(bars[i]), _c(bars[i]), _v(bars[i])
        if o is None or c is None:
            out.append(None)
            continue
        out.append(evr_bar(abs(c - o), a, v if v is not None else 0.0, vma))
    return out


# ─────────────────────────── convenience bundle ───────────────────────────

def compute_all(bars: Sequence[Bar]) -> dict[str, float | None]:
    """One-shot summary of the T0 metrics over a bar series (for sanity checks / logging)."""
    evr = effort_vs_result(bars)
    evr_last = next((x for x in reversed(evr) if x is not None), None)
    return {
        "n_bars": len(bars),
        "bar_pressure": bar_pressure(bars),
        "corwin_schultz_spread": corwin_schultz_spread(bars),
        "abdi_ranaldo_spread": abdi_ranaldo_spread(bars),
        "spread_estimate": spread_estimate(bars),
        "amihud_illiq": amihud_illiq(bars),
        "evr_last": evr_last,
    }
