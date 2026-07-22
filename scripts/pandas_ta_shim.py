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


# ── V5 technicals (2026-07-22): the four functions the engine calls that the
#    shim previously LACKED — their absence silently degraded OBV/CMF/ADX/Aroon
#    to NEUTRAL via the engine's nonfatal handlers. Formula parity with
#    pandas_ta (column names included) is test-enforced.

def obv(close: pd.Series, volume: pd.Series, **_):
    """On-Balance Volume: cumulative signed volume."""
    direction = close.diff().apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    direction.iloc[0] = 0.0
    return (direction * volume).cumsum()


def cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
        length: int = 20, **_):
    """Chaikin Money Flow: sum(MFV, n) / sum(volume, n)."""
    rng = (high - low).replace(0.0, pd.NA)
    mfm = ((close - low) - (high - close)) / rng
    mfv = (mfm * volume).fillna(0.0)
    return mfv.rolling(length, min_periods=length).sum() / \
        volume.rolling(length, min_periods=length).sum()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14, **_):
    """Wilder ADX with +DI/−DI. Columns match pandas_ta: ADX_{l}, DMP_{l}, DMN_{l}."""
    up = high.diff()
    dn = -low.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    tr = true_range(high, low, close)
    atr_w = _wilder(tr, length)
    plus_di = 100.0 * _wilder(plus_dm.fillna(0.0), length) / atr_w
    minus_di = 100.0 * _wilder(minus_dm.fillna(0.0), length) / atr_w
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, pd.NA)
    adx_s = _wilder(dx.fillna(0.0), length)
    return pd.DataFrame({f"ADX_{length}": adx_s,
                         f"DMP_{length}": plus_di,
                         f"DMN_{length}": minus_di})


def aroon(high: pd.Series, low: pd.Series, length: int = 25, **_):
    """Aroon up/down. Columns match pandas_ta: AROOND_{l}, AROONU_{l}, AROONOSC_{l}."""
    def _since_max(x):
        return float(len(x) - 1 - x.argmax())

    def _since_min(x):
        return float(len(x) - 1 - x.argmin())
    bars_hi = high.rolling(length + 1, min_periods=length + 1).apply(_since_max, raw=True)
    bars_lo = low.rolling(length + 1, min_periods=length + 1).apply(_since_min, raw=True)
    up_s = 100.0 * (length - bars_hi) / length
    dn_s = 100.0 * (length - bars_lo) / length
    return pd.DataFrame({f"AROOND_{length}": dn_s,
                         f"AROONU_{length}": up_s,
                         f"AROONOSC_{length}": up_s - dn_s})
