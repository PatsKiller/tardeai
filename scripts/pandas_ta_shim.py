#!/usr/bin/env python3
"""pandas_ta_shim.py — drop-in replacement for the pandas_ta functions this repo uses.

WHY: scripts/indicator_engine.py imports pandas_ta, which cannot be installed in
this environment (pandas 3.0.2 / numpy 2.4.4 / Python 3.14 — no matching
distribution; the package is effectively abandoned). The engine therefore died at
import on every run: 463 RETRY_EXHAUSTED events and a standing SIEM P1, while
broker_proposal_intel, api_v2, indicator_cache_refresh and agent_collab consume
its output.

CONTRACT: indicator_engine indexes pandas_ta's exact column names
(MACD_12_26_9, BBL_20_2.0_2.0, STOCHk_14_3_3, KCLe_20_2.0 ...), so this shim
reproduces those names exactly. Formulas follow the same conventions pandas_ta
uses — notably Wilder's smoothing (alpha = 1/length) for RSI and ATR, which is
what makes the values comparable to the previous behaviour rather than merely
plausible.

Everything returns pandas objects with NaN warm-up periods preserved, because
callers rely on .dropna().iloc[-1].
"""
from __future__ import annotations

import pandas as pd


def _wilder(series: pd.Series, length: int) -> pd.Series:
    """Wilder's smoothing — pandas_ta's default for RSI/ATR (alpha = 1/length)."""
    return series.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def sma(close: pd.Series, length: int = 10, **_):
    return close.rolling(window=length, min_periods=length).mean()


def ema(close: pd.Series, length: int = 10, **_):
    return close.ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(close: pd.Series, length: int = 14, **_):
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = _wilder(gain, length)
    avg_loss = _wilder(loss, length)
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss == 0 -> RSI 100 (pandas_ta behaviour), not NaN
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return out


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    return pd.concat([(high - low).abs(),
                      (high - prev).abs(),
                      (low - prev).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14, **_):
    return _wilder(true_range(high, low, close), length)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9, **_):
    fast_e = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_e = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    line = fast_e - slow_e
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = line - sig
    return pd.DataFrame({
        f"MACD_{fast}_{slow}_{signal}": line,
        f"MACDh_{fast}_{slow}_{signal}": hist,
        f"MACDs_{fast}_{slow}_{signal}": sig,
    })


def bbands(close: pd.Series, length: int = 20, std: float = 2.0, **_):
    mid = close.rolling(window=length, min_periods=length).mean()
    # pandas_ta uses the population standard deviation (ddof=0).
    sd = close.rolling(window=length, min_periods=length).std(ddof=0)
    upper = mid + std * sd
    lower = mid - std * sd
    bandwidth = (upper - lower) / mid * 100.0
    pct_b = (close - lower) / (upper - lower)
    suffix = f"{length}_{std}_{std}"
    return pd.DataFrame({
        f"BBL_{suffix}": lower,
        f"BBM_{suffix}": mid,
        f"BBU_{suffix}": upper,
        f"BBB_{suffix}": bandwidth,
        f"BBP_{suffix}": pct_b,
    })


def stoch(high: pd.Series, low: pd.Series, close: pd.Series,
          k: int = 14, d: int = 3, smooth_k: int = 3, **_):
    ll = low.rolling(window=k, min_periods=k).min()
    hh = high.rolling(window=k, min_periods=k).max()
    raw = 100.0 * (close - ll) / (hh - ll)
    k_line = raw.rolling(window=smooth_k, min_periods=smooth_k).mean()
    d_line = k_line.rolling(window=d, min_periods=d).mean()
    return pd.DataFrame({
        f"STOCHk_{k}_{d}_{smooth_k}": k_line,
        f"STOCHd_{k}_{d}_{smooth_k}": d_line,
    })


def willr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14, **_):
    hh = high.rolling(window=length, min_periods=length).max()
    ll = low.rolling(window=length, min_periods=length).min()
    return -100.0 * (hh - close) / (hh - ll)


def kc(high: pd.Series, low: pd.Series, close: pd.Series,
       length: int = 20, scalar: float = 2.0, **_):
    """Keltner Channels. pandas_ta's default basis is an EMA -> 'e' column suffix."""
    basis = close.ewm(span=length, adjust=False, min_periods=length).mean()
    rng = _wilder(true_range(high, low, close), length)
    return pd.DataFrame({
        f"KCLe_{length}_{scalar}": basis - scalar * rng,
        f"KCBe_{length}_{scalar}": basis,
        f"KCUe_{length}_{scalar}": basis + scalar * rng,
    })
