"""
indicator_engine.py
Technical indicator computation engine for Trade AI v12.
Computes 17+ indicator strategies and scores confluence.
Called by: api_v2.py, scoring.py, continuous_runner.py, agent jobs
Config: config/indicator_strategies.yaml
Cache: indicator_confluence_cache (DB), indicator_signal_history (DB)
Non-fatal: all indicator failures return NEUTRAL, never crash caller.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd
try:
    import pandas_ta as ta
except ModuleNotFoundError:
    # pandas_ta has no distribution for this environment (pandas 3.x / numpy 2.x /
    # py3.14) and the import failure killed every run — 463 RETRY_EXHAUSTED events
    # and a standing SIEM P1 (2026-07-20). The shim reproduces the exact function
    # signatures and column names this module indexes.
    import pandas_ta_shim as ta
import yaml
import yfinance as yf

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

logger = logging.getLogger(__name__)

# Load config once at module import
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'indicator_strategies.yaml')


def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load indicator config: {e}")
        return {}


CONFIG = _load_config()

# ── OHLCV Data Fetcher ───────────────────────────────────────────────────────

_price_cache = {}  # in-memory cache: key -> (df, fetched_at)
CACHE_SECONDS = 900  # 15 min


def _fetch_ohlcv(symbol: str, days: int = 90) -> Optional[pd.DataFrame]:
    """Fetch OHLCV from yfinance with in-memory cache.
    Handles MultiIndex columns. Returns None on failure (non-fatal)."""
    cache_key = f"{symbol}_{days}"
    if cache_key in _price_cache:
        df, fetched_at = _price_cache[cache_key]
        if (datetime.now() - fetched_at).seconds < CACHE_SECONDS:
            return df.copy()

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{days}d", interval="1d", auto_adjust=True)

        if df is None or df.empty:
            logger.warning(f"No OHLCV data returned for {symbol}")
            return None

        # Handle MultiIndex columns (yfinance sometimes returns these)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # Standardize column names
        df.columns = [c.lower() for c in df.columns]

        # Require minimum data
        if len(df) < 20:
            logger.warning(f"Insufficient OHLCV data for {symbol}: {len(df)} rows")
            return None

        _price_cache[cache_key] = (df, datetime.now())
        return df.copy()

    except Exception as e:
        logger.warning(f"OHLCV fetch failed for {symbol} (non-fatal): {e}")
        return None


def _neutral(details=None):
    return {'signal': 'NEUTRAL', 'value': None, 'details': details or {}}


def _unavailable(reason, details=None):
    """V5 (2026-07-22): a computation FAILURE or missing implementation is NOT a
    neutral market read — silent NEUTRAL made the engine look more complete than
    it was (obv/cmf/adx/aroon under the pandas_ta shim). UNAVAILABLE is excluded
    from confluence and rendered gray, never counted as evidence."""
    d = dict(details or {})
    d['error'] = str(reason)[:160]
    return {'signal': 'UNAVAILABLE', 'value': None, 'details': d}


# ── Individual Indicator Functions ────────────────────────────────────────────

def _compute_rsi(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 14)
        rsi_series = ta.rsi(df['close'], length=period)
        if rsi_series is None or rsi_series.dropna().empty:
            return _unavailable('insufficient_bars')
        rsi_val = float(rsi_series.dropna().iloc[-1])

        # Divergence: last N bars price higher but RSI lower
        window = cfg.get('divergence_window', 5)
        divergence = False
        if len(rsi_series.dropna()) >= window and len(df) >= window:
            price_slice = df['close'].iloc[-window:]
            rsi_slice = rsi_series.dropna().iloc[-window:]
            if len(rsi_slice) >= window:
                if price_slice.iloc[-1] > price_slice.iloc[0] and rsi_slice.iloc[-1] < rsi_slice.iloc[0]:
                    divergence = True  # bearish divergence

        oversold = cfg.get('oversold', 30)
        overbought = cfg.get('overbought', 70)
        entry_max = cfg.get('entry_max', 55)

        # Entry quality
        if rsi_val < 40:
            eq = 'good'
        elif rsi_val < entry_max:
            eq = 'ok'
        else:
            eq = 'poor'

        if rsi_val < oversold:
            signal = 'BULLISH'
        elif rsi_val < entry_max and len(rsi_series.dropna()) >= 3:
            # RSI rising from below 50
            recent = rsi_series.dropna().iloc[-3:]
            if float(recent.iloc[-1]) > float(recent.iloc[0]) and rsi_val < 50:
                signal = 'BULLISH'
            elif rsi_val > overbought:
                signal = 'BEARISH'
            else:
                signal = 'NEUTRAL'
        elif rsi_val > overbought:
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        # Bearish divergence overrides if RSI is elevated
        if divergence and rsi_val > 55:
            signal = 'BEARISH'

        return {'signal': signal, 'value': round(rsi_val, 2),
                'details': {'rsi': round(rsi_val, 2), 'divergence': divergence, 'entry_quality': eq}}
    except Exception as e:
        logger.warning(f"RSI computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_stochastic(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        k_period = cfg.get('k_period', 14)
        d_period = cfg.get('d_period', 3)
        smooth = cfg.get('smooth', 3)
        result = ta.stoch(df['high'], df['low'], df['close'],
                          k=k_period, d=d_period, smooth_k=smooth)
        if result is None or result.dropna().empty:
            return _unavailable('insufficient_bars')

        k_col = f'STOCHk_{k_period}_{d_period}_{smooth}'
        d_col = f'STOCHd_{k_period}_{d_period}_{smooth}'
        k_val = float(result[k_col].dropna().iloc[-1])
        d_val = float(result[d_col].dropna().iloc[-1])

        oversold = cfg.get('oversold', 20)
        overbought = cfg.get('overbought', 80)

        crossover = None
        if len(result.dropna()) >= 2:
            prev_k = float(result[k_col].dropna().iloc[-2])
            prev_d = float(result[d_col].dropna().iloc[-2])
            if prev_k <= prev_d and k_val > d_val and k_val < oversold + 20:
                crossover = 'bullish'
            elif prev_k >= prev_d and k_val < d_val and k_val > overbought - 20:
                crossover = 'bearish'

        if crossover == 'bullish' or (k_val < oversold and d_val < oversold):
            signal = 'BULLISH'
        elif crossover == 'bearish' or (k_val > overbought and d_val > overbought):
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(k_val, 2),
                'details': {'k': round(k_val, 2), 'd': round(d_val, 2), 'crossover': crossover}}
    except Exception as e:
        logger.warning(f"Stochastic computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_macd(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        fast = cfg.get('fast', 12)
        slow = cfg.get('slow', 26)
        sig = cfg.get('signal', 9)
        result = ta.macd(df['close'], fast=fast, slow=slow, signal=sig)
        if result is None or result.dropna().empty:
            return _unavailable('insufficient_bars')

        macd_col = f'MACD_{fast}_{slow}_{sig}'
        hist_col = f'MACDh_{fast}_{slow}_{sig}'
        sig_col = f'MACDs_{fast}_{slow}_{sig}'

        macd_val = float(result[macd_col].dropna().iloc[-1])
        hist_val = float(result[hist_col].dropna().iloc[-1])
        sig_val = float(result[sig_col].dropna().iloc[-1])

        # Histogram direction
        hist_dir = 'flat'
        if len(result[hist_col].dropna()) >= 2:
            prev_hist = float(result[hist_col].dropna().iloc[-2])
            if hist_val > prev_hist:
                hist_dir = 'up'
            elif hist_val < prev_hist:
                hist_dir = 'down'

        # Signal line crossover
        signal = 'NEUTRAL'
        if len(result.dropna()) >= 2:
            prev_macd = float(result[macd_col].dropna().iloc[-2])
            prev_sig = float(result[sig_col].dropna().iloc[-2])
            if prev_macd <= prev_sig and macd_val > sig_val:
                signal = 'BULLISH'
            elif prev_macd >= prev_sig and macd_val < sig_val:
                signal = 'BEARISH'

        # Histogram flip
        if signal == 'NEUTRAL' and len(result[hist_col].dropna()) >= 2:
            prev_hist = float(result[hist_col].dropna().iloc[-2])
            if prev_hist <= 0 and hist_val > 0:
                signal = 'BULLISH'
            elif prev_hist >= 0 and hist_val < 0:
                signal = 'BEARISH'

        return {'signal': signal, 'value': round(macd_val, 4),
                'details': {'macd': round(macd_val, 4), 'signal': round(sig_val, 4),
                            'histogram': round(hist_val, 4), 'histogram_direction': hist_dir}}
    except Exception as e:
        logger.warning(f"MACD computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_williams_r(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 14)
        wr = ta.willr(df['high'], df['low'], df['close'], length=period)
        if wr is None or wr.dropna().empty:
            return _unavailable('insufficient_bars')
        wr_val = float(wr.dropna().iloc[-1])

        oversold = cfg.get('oversold', -80)
        overbought = cfg.get('overbought', -20)

        if wr_val < oversold:
            signal = 'BULLISH'
        elif wr_val > overbought:
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(wr_val, 2),
                'details': {'williams_r': round(wr_val, 2)}}
    except Exception as e:
        logger.warning(f"Williams %R computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_ema(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        periods = cfg.get('periods', [9, 21, 50, 200])
        ema_vals = {}
        for p in periods:
            ema = ta.ema(df['close'], length=p)
            if ema is not None and not ema.dropna().empty:
                ema_vals[p] = float(ema.dropna().iloc[-1])

        if not ema_vals:
            return _neutral()

        current_price = float(df['close'].iloc[-1])

        # Check price above all EMAs
        price_above_all = all(current_price > v for v in ema_vals.values())
        price_below_all = all(current_price < v for v in ema_vals.values())

        # Golden Cross / Death Cross
        golden_cross = False
        death_cross = False
        if 50 in ema_vals and 200 in ema_vals:
            golden_cross = ema_vals[50] > ema_vals[200]
            death_cross = ema_vals[50] < ema_vals[200]

        # Crossover pairs
        crossover_pairs = cfg.get('crossover_pairs', [[9, 21], [50, 200]])
        bullish_crosses = 0
        bearish_crosses = 0
        for pair in crossover_pairs:
            short_p, long_p = pair
            if short_p in ema_vals and long_p in ema_vals:
                if ema_vals[short_p] > ema_vals[long_p]:
                    bullish_crosses += 1
                else:
                    bearish_crosses += 1

        if price_above_all and bullish_crosses >= len(crossover_pairs):
            signal = 'BULLISH'
        elif price_below_all and bearish_crosses >= len(crossover_pairs):
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        details = {f'ema_{p}': round(v, 2) for p, v in ema_vals.items()}
        details['golden_cross'] = golden_cross
        details['death_cross'] = death_cross
        details['price_above_all'] = price_above_all

        return {'signal': signal, 'value': round(current_price, 2), 'details': details}
    except Exception as e:
        logger.warning(f"EMA computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_sma(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        periods = cfg.get('periods', [20, 50, 200])
        sma_vals = {}
        for p in periods:
            sma = ta.sma(df['close'], length=p)
            if sma is not None and not sma.dropna().empty:
                sma_vals[p] = float(sma.dropna().iloc[-1])

        if not sma_vals:
            return _neutral()

        current_price = float(df['close'].iloc[-1])

        # Perfect alignment check
        alignment = 'neutral'
        if 20 in sma_vals and 50 in sma_vals:
            if current_price > sma_vals[20] and sma_vals[20] > sma_vals[50]:
                if 200 in sma_vals and sma_vals[50] > sma_vals[200]:
                    alignment = 'bullish'
                elif 200 not in sma_vals:
                    alignment = 'bullish'
            elif current_price < sma_vals[20] and sma_vals[20] < sma_vals[50]:
                alignment = 'bearish'

        if alignment == 'bullish':
            signal = 'BULLISH'
        elif alignment == 'bearish':
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        details = {f'sma_{p}': round(v, 2) for p, v in sma_vals.items()}
        details['alignment'] = alignment

        return {'signal': signal, 'value': round(current_price, 2), 'details': details}
    except Exception as e:
        logger.warning(f"SMA computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_vwap(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        # Rolling 20-day VWAP approximation for daily bars
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        cum_tp_vol = (typical_price * df['volume']).rolling(window=20).sum()
        cum_vol = df['volume'].rolling(window=20).sum()
        vwap = cum_tp_vol / cum_vol

        if vwap.dropna().empty:
            return _neutral()

        vwap_val = float(vwap.dropna().iloc[-1])
        current_price = float(df['close'].iloc[-1])
        proximity_pct = cfg.get('proximity_pct', 0.5)

        distance_pct = ((current_price - vwap_val) / vwap_val) * 100

        if current_price > vwap_val:
            position = 'above'
        elif abs(distance_pct) <= proximity_pct:
            position = 'at'
        else:
            position = 'below'

        # Bullish if price above VWAP or reclaiming from near it
        if position == 'above' and abs(distance_pct) <= proximity_pct * 3:
            signal = 'BULLISH'
        elif position == 'below' and abs(distance_pct) > proximity_pct:
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(vwap_val, 2),
                'details': {'vwap': round(vwap_val, 2), 'distance_pct': round(distance_pct, 2),
                            'position': position}}
    except Exception as e:
        logger.warning(f"VWAP computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_bollinger(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 20)
        std_dev = cfg.get('std_dev', 2.0)
        result = ta.bbands(df['close'], length=period, std=std_dev)
        if result is None or result.dropna().empty:
            return _unavailable('insufficient_bars')

        suffix = f'{period}_{std_dev}_{std_dev}'
        lower = float(result[f'BBL_{suffix}'].dropna().iloc[-1])
        middle = float(result[f'BBM_{suffix}'].dropna().iloc[-1])
        upper = float(result[f'BBU_{suffix}'].dropna().iloc[-1])
        bandwidth = float(result[f'BBB_{suffix}'].dropna().iloc[-1])
        pct_b = float(result[f'BBP_{suffix}'].dropna().iloc[-1])

        squeeze_threshold = cfg.get('squeeze_threshold', 0.02)
        current_price = float(df['close'].iloc[-1])

        # Bandwidth is already percentage-based from pandas_ta
        squeeze = bandwidth < (squeeze_threshold * 100)

        # Check if expanding
        expanding = False
        if len(result[f'BBB_{suffix}'].dropna()) >= 3:
            prev_bw = float(result[f'BBB_{suffix}'].dropna().iloc[-3])
            expanding = bandwidth > prev_bw

        if squeeze:
            signal = 'NEUTRAL'  # wait for breakout
        elif pct_b < 0.1 and expanding:
            signal = 'BULLISH'  # near lower band, expanding
        elif pct_b > 0.9 and not expanding:
            signal = 'BEARISH'  # near upper band, contracting
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(pct_b, 4),
                'details': {'upper': round(upper, 2), 'middle': round(middle, 2),
                            'lower': round(lower, 2), 'percent_b': round(pct_b, 4),
                            'bandwidth': round(bandwidth, 4), 'squeeze': squeeze,
                            'expanding': expanding}}
    except Exception as e:
        logger.warning(f"Bollinger computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_keltner(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 20)
        atr_mult = cfg.get('atr_multiple', 2.0)
        kc = ta.kc(df['high'], df['low'], df['close'], length=period, scalar=atr_mult)
        if kc is None or kc.dropna().empty:
            return _unavailable('insufficient_bars')

        kc_lower = float(kc[f'KCLe_{period}_{atr_mult}'].dropna().iloc[-1])
        kc_middle = float(kc[f'KCBe_{period}_{atr_mult}'].dropna().iloc[-1])
        kc_upper = float(kc[f'KCUe_{period}_{atr_mult}'].dropna().iloc[-1])

        # TTM Squeeze: compare with Bollinger Bands
        bb = ta.bbands(df['close'], length=20, std=2.0)
        squeeze_on = False
        squeeze_fired = False
        direction = None

        if bb is not None and not bb.dropna().empty:
            bb_lower = float(bb['BBL_20_2.0_2.0'].dropna().iloc[-1])
            bb_upper = float(bb['BBU_20_2.0_2.0'].dropna().iloc[-1])
            # Squeeze ON if BB inside KC
            squeeze_on = bb_lower > kc_lower and bb_upper < kc_upper

            # Check previous bar for squeeze state change
            if len(bb.dropna()) >= 2 and len(kc.dropna()) >= 2:
                prev_bb_l = float(bb['BBL_20_2.0_2.0'].dropna().iloc[-2])
                prev_bb_u = float(bb['BBU_20_2.0_2.0'].dropna().iloc[-2])
                prev_kc_l = float(kc[f'KCLe_{period}_{atr_mult}'].dropna().iloc[-2])
                prev_kc_u = float(kc[f'KCUe_{period}_{atr_mult}'].dropna().iloc[-2])
                prev_squeeze = prev_bb_l > prev_kc_l and prev_bb_u < prev_kc_u

                if prev_squeeze and not squeeze_on:
                    squeeze_fired = True
                    current_price = float(df['close'].iloc[-1])
                    if current_price > kc_middle:
                        direction = 'bullish'
                    else:
                        direction = 'bearish'

        current_price = float(df['close'].iloc[-1])
        if squeeze_fired and direction == 'bullish':
            signal = 'BULLISH'
        elif squeeze_fired and direction == 'bearish':
            signal = 'BEARISH'
        elif squeeze_on:
            signal = 'NEUTRAL'
        elif current_price > kc_upper:
            signal = 'BULLISH'
        elif current_price < kc_lower:
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(kc_middle, 2),
                'details': {'upper': round(kc_upper, 2), 'middle': round(kc_middle, 2),
                            'lower': round(kc_lower, 2), 'squeeze_on': squeeze_on,
                            'squeeze_fired': squeeze_fired, 'direction': direction}}
    except Exception as e:
        logger.warning(f"Keltner computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_atr(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 14)
        atr_series = ta.atr(df['high'], df['low'], df['close'], length=period)
        if atr_series is None or atr_series.dropna().empty:
            return _unavailable('insufficient_bars')

        atr_val = float(atr_series.dropna().iloc[-1])
        current_price = float(df['close'].iloc[-1])

        # ATR percentile over available data
        atr_clean = atr_series.dropna()
        if len(atr_clean) > 10:
            pct_rank = float((atr_clean < atr_val).sum() / len(atr_clean) * 100)
        else:
            pct_rank = 50.0

        low_t = cfg.get('volatility_percentile_low', 25)
        high_t = cfg.get('volatility_percentile_high', 75)

        if pct_rank < low_t:
            regime = 'low'
        elif pct_rank < high_t:
            regime = 'normal'
        elif pct_rank < 90:
            regime = 'high'
        else:
            regime = 'extreme'

        if regime in ('low', 'normal'):
            signal = 'BULLISH'  # good conditions for entry
        elif regime == 'extreme':
            signal = 'BEARISH'  # too volatile
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(atr_val, 4),
                'details': {'atr': round(atr_val, 4), 'atr_pct': round(pct_rank, 1),
                            'regime': regime,
                            'stop_1x': round(current_price - atr_val, 2),
                            'target_1x': round(current_price + atr_val, 2)}}
    except Exception as e:
        logger.warning(f"ATR computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_fibonacci(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        lookback_swing = cfg.get('lookback_swing', 20)
        lookback_annual = min(cfg.get('lookback_annual', 252), len(df))
        proximity_pct = cfg.get('proximity_pct', 2.0)
        ret_levels = cfg.get('retracement_levels', [0.236, 0.382, 0.5, 0.618, 0.786])
        ext_levels = cfg.get('extension_levels', [1.272, 1.618, 2.618])

        current_price = float(df['close'].iloc[-1])

        # Swing levels (recent)
        swing_high = float(df['high'].iloc[-lookback_swing:].max())
        swing_low = float(df['low'].iloc[-lookback_swing:].min())
        swing_range = swing_high - swing_low

        # Compute retracement levels (from high to low for downtrend retracement)
        key_levels = {}
        for level in ret_levels:
            price_level = swing_high - (swing_range * level)
            key_levels[f'ret_{level}'] = round(price_level, 2)

        # Extension levels
        extensions = {}
        for level in ext_levels:
            ext_price = swing_low + (swing_range * level)
            extensions[f'ext_{level}'] = round(ext_price, 2)

        # Check proximity to fib levels
        at_level = False
        nearest_level = None
        nearest_pct = 999.0
        nearest_label = None

        for label, price_level in key_levels.items():
            dist = abs((current_price - price_level) / price_level * 100)
            if dist < nearest_pct:
                nearest_pct = dist
                nearest_level = price_level
                nearest_label = label
            if dist < proximity_pct:
                at_level = True

        signal = 'NEUTRAL'
        if at_level and nearest_level:
            # At a fib level — bullish if bouncing off support, bearish if rejected at resistance
            fib_val = float(nearest_label.split('_')[1]) if nearest_label else 0.5
            if fib_val >= 0.382 and current_price >= nearest_level:
                signal = 'BULLISH'  # holding above key fib support
            elif current_price < nearest_level:
                signal = 'BEARISH'  # rejected at fib resistance

        return {'signal': signal, 'value': nearest_level,
                'details': {'at_level': at_level, 'nearest_level': nearest_level,
                            'nearest_pct': round(nearest_pct, 2),
                            'nearest_label': nearest_label,
                            'key_levels': key_levels, 'extensions': extensions,
                            'swing_high': round(swing_high, 2),
                            'swing_low': round(swing_low, 2)}}
    except Exception as e:
        logger.warning(f"Fibonacci computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_pivots(df: pd.DataFrame, cfg: dict, timeframe: str = 'daily') -> dict:
    """Generic pivot computation for daily/weekly/fibonacci."""
    try:
        proximity_pct = cfg.get('proximity_pct', 0.5)
        current_price = float(df['close'].iloc[-1])

        if timeframe == 'weekly':
            # Find prior week data
            if len(df) < 7:
                return _neutral()
            # Use the 5 trading days before the last day
            prior_data = df.iloc[-6:-1]
            h = float(prior_data['high'].max())
            l = float(prior_data['low'].min())
            c = float(prior_data['close'].iloc[-1])
        else:
            # Daily: use prior day
            if len(df) < 2:
                return _neutral()
            prior = df.iloc[-2]
            h = float(prior['high'])
            l = float(prior['low'])
            c = float(prior['close'])

        pp = (h + l + c) / 3

        if timeframe == 'fibonacci':
            rng = h - l
            r1 = pp + 0.382 * rng
            r2 = pp + 0.618 * rng
            r3 = pp + rng
            s1 = pp - 0.382 * rng
            s2 = pp - 0.618 * rng
            s3 = pp - rng
        else:
            r1 = 2 * pp - l
            r2 = pp + (h - l)
            r3 = h + 2 * (pp - l)
            s1 = 2 * pp - h
            s2 = pp - (h - l)
            s3 = l - 2 * (h - pp)

        levels = {'pp': pp, 'r1': r1, 'r2': r2, 'r3': r3, 's1': s1, 's2': s2, 's3': s3}
        levels = {k: round(v, 2) for k, v in levels.items()}

        # Find nearest level
        nearest = None
        nearest_dist = 999.0
        for name, val in levels.items():
            dist = abs((current_price - val) / val * 100)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = name

        signal = 'NEUTRAL'
        if nearest and nearest_dist < proximity_pct:
            if nearest.startswith('s'):
                signal = 'BULLISH'  # at support level
            elif nearest.startswith('r'):
                signal = 'BEARISH'  # at resistance level

        levels['nearest'] = nearest
        return {'signal': signal, 'value': levels.get('pp'), 'details': levels}
    except Exception as e:
        logger.warning(f"Pivot ({timeframe}) computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_pivots_daily(df: pd.DataFrame, cfg: dict) -> dict:
    return _compute_pivots(df, cfg, 'daily')


def _compute_pivots_weekly(df: pd.DataFrame, cfg: dict) -> dict:
    return _compute_pivots(df, cfg, 'weekly')


def _compute_pivots_fibonacci(df: pd.DataFrame, cfg: dict) -> dict:
    return _compute_pivots(df, cfg, 'fibonacci')


def _compute_volume_profile(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        lookback = cfg.get('lookback', 20)
        node_threshold = cfg.get('node_threshold', 1.5)
        recent = df.iloc[-lookback:]

        if 'volume' not in recent.columns or recent['volume'].sum() == 0:
            return _neutral()

        avg_vol = float(recent['volume'].mean())
        current_vol = float(recent['volume'].iloc[-1])
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

        # High volume node
        is_hvn = vol_ratio >= node_threshold
        current_price = float(recent['close'].iloc[-1])
        prev_price = float(recent['close'].iloc[-2]) if len(recent) >= 2 else current_price

        if is_hvn and current_price > prev_price:
            signal = 'BULLISH'
        elif is_hvn and current_price < prev_price:
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(vol_ratio, 2),
                'details': {'volume_ratio': round(vol_ratio, 2), 'is_hvn': is_hvn,
                            'avg_volume': round(avg_vol, 0)}}
    except Exception as e:
        logger.warning(f"Volume profile computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_obv(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        obv = ta.obv(df['close'], df['volume'])
        if obv is None or obv.dropna().empty:
            return _unavailable('insufficient_bars')

        obv_val = float(obv.dropna().iloc[-1])
        window = cfg.get('divergence_window', 5)

        # OBV trend over last N bars
        obv_trend = 'flat'
        divergence = False
        if len(obv.dropna()) >= window:
            obv_slice = obv.dropna().iloc[-window:]
            price_slice = df['close'].iloc[-window:]

            obv_change = float(obv_slice.iloc[-1] - obv_slice.iloc[0])
            price_change = float(price_slice.iloc[-1] - price_slice.iloc[0])

            if obv_change > 0:
                obv_trend = 'up'
            elif obv_change < 0:
                obv_trend = 'down'

            # Divergence: OBV and price moving in opposite directions
            if price_change <= 0 and obv_change > 0:
                divergence = True  # accumulation — bullish

        if obv_trend == 'up' or divergence:
            signal = 'BULLISH'
        elif obv_trend == 'down':
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(obv_val, 0),
                'details': {'obv': round(obv_val, 0), 'obv_trend': obv_trend,
                            'divergence': divergence}}
    except Exception as e:
        logger.warning(f"OBV computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_volume_roc(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 20)
        breakout_t = cfg.get('breakout_threshold', 2.0)
        institutional_t = cfg.get('institutional_threshold', 5.0)

        if 'volume' not in df.columns:
            return _unavailable('insufficient_bars')

        avg_vol = float(df['volume'].iloc[-period:].mean()) if len(df) >= period else float(df['volume'].mean())
        current_vol = float(df['volume'].iloc[-1])

        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        price_change = float(df['close'].iloc[-1] - df['close'].iloc[-2]) if len(df) >= 2 else 0

        if vol_ratio >= institutional_t:
            classification = 'institutional'
        elif vol_ratio >= breakout_t:
            classification = 'breakout'
        elif vol_ratio >= 0.5:
            classification = 'normal'
        else:
            classification = 'thin'

        if vol_ratio >= breakout_t and price_change > 0:
            signal = 'BULLISH'
        elif vol_ratio >= breakout_t and price_change < 0:
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(vol_ratio, 2),
                'details': {'volume_ratio': round(vol_ratio, 2),
                            'avg_volume': round(avg_vol, 0),
                            'classification': classification}}
    except Exception as e:
        logger.warning(f"Volume ROC computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_cmf(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 20)
        cmf = ta.cmf(df['high'], df['low'], df['close'], df['volume'], length=period)
        if cmf is None or cmf.dropna().empty:
            return _unavailable('insufficient_bars')

        cmf_val = float(cmf.dropna().iloc[-1])
        acc_t = cfg.get('accumulation', 0.1)
        dist_t = cfg.get('distribution', -0.1)

        if cmf_val > acc_t:
            signal = 'BULLISH'
            flow = 'accumulation'
        elif cmf_val < dist_t:
            signal = 'BEARISH'
            flow = 'distribution'
        else:
            signal = 'NEUTRAL'
            flow = 'neutral'

        return {'signal': signal, 'value': round(cmf_val, 4),
                'details': {'cmf': round(cmf_val, 4), 'flow': flow}}
    except Exception as e:
        logger.warning(f"CMF computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_adx(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 14)
        result = ta.adx(df['high'], df['low'], df['close'], length=period)
        if result is None or result.dropna().empty:
            return _unavailable('insufficient_bars')

        adx_val = float(result[f'ADX_{period}'].dropna().iloc[-1])
        plus_di = float(result[f'DMP_{period}'].dropna().iloc[-1])
        minus_di = float(result[f'DMN_{period}'].dropna().iloc[-1])

        trending = cfg.get('trending', 25)
        ranging = cfg.get('ranging', 20)

        if adx_val < ranging:
            regime = 'ranging'
        elif adx_val < trending:
            regime = 'moderate'
        else:
            regime = 'trending'

        if adx_val >= trending and plus_di > minus_di:
            signal = 'BULLISH'
        elif adx_val >= trending and minus_di > plus_di:
            signal = 'BEARISH'
        else:
            signal = 'NEUTRAL'

        return {'signal': signal, 'value': round(adx_val, 2),
                'details': {'adx': round(adx_val, 2), 'plus_di': round(plus_di, 2),
                            'minus_di': round(minus_di, 2), 'regime': regime}}
    except Exception as e:
        logger.warning(f"ADX computation failed (non-fatal): {e}")
        return _unavailable(e)


def _compute_aroon(df: pd.DataFrame, cfg: dict) -> dict:
    try:
        period = cfg.get('period', 25)
        result = ta.aroon(df['high'], df['low'], length=period)
        if result is None or result.dropna().empty:
            return _unavailable('insufficient_bars')

        aroon_up = float(result[f'AROONU_{period}'].dropna().iloc[-1])
        aroon_down = float(result[f'AROOND_{period}'].dropna().iloc[-1])

        strong = cfg.get('strong', 70)
        weak = cfg.get('weak', 30)

        if aroon_up > strong and aroon_down < weak:
            signal = 'BULLISH'
            trend = 'up'
        elif aroon_down > strong and aroon_up < weak:
            signal = 'BEARISH'
            trend = 'down'
        else:
            signal = 'NEUTRAL'
            trend = 'none'

        return {'signal': signal, 'value': round(aroon_up, 2),
                'details': {'aroon_up': round(aroon_up, 2), 'aroon_down': round(aroon_down, 2),
                            'trend': trend}}
    except Exception as e:
        logger.warning(f"Aroon computation failed (non-fatal): {e}")
        return _unavailable(e)


# ── V5 confluence v2: weighted, family-grouped, correlation-capped (17.8) ─────
# Correlated indicators must not multiply confirmation: EMA+SMA are one TREND
# read; RSI+Williams%R are one oscillator read. Each signal contributes its
# CONFIGURED YAML weight (finally applied — the legacy counter never read them),
# capped per evidence family, and STRONG requires >=3 independent families.
EVIDENCE_FAMILIES = {
    'TREND': ('ema', 'sma', 'adx', 'aroon'),
    'MOMENTUM': ('rsi', 'stochastic', 'macd', 'williams_r'),
    'VOLUME_FLOW': ('vwap', 'obv', 'volume_roc', 'cmf', 'volume_profile'),
    'VOLATILITY': ('bollinger', 'keltner', 'atr'),
    'LEVEL': ('fibonacci', 'pivots_daily', 'pivots_weekly', 'pivots_fibonacci'),
}
FAMILY_CAP = 2.0          # max weighted contribution per family per direction
STRONG_MIN_FAMILIES = 3   # no single family may create STRONG confluence alone


def analyze_confluence_v2(signals: dict, strategy_cfgs: dict | None = None) -> dict:
    """Pure: signals {name: {signal, value, details}} -> family-capped weighted
    confluence. UNAVAILABLE/FAILED/STALE signals are excluded from scoring and
    listed, never counted as neutral evidence."""
    strategy_cfgs = strategy_cfgs or (CONFIG.get('strategies', {}) if CONFIG else {})
    fam_of = {ind: fam for fam, inds in EVIDENCE_FAMILIES.items() for ind in inds}
    fams: dict = {}
    contributors, detractors, neutral, unavailable = [], [], [], []
    for name, sig in (signals or {}).items():
        state = str((sig or {}).get('signal') or 'UNAVAILABLE').upper()
        w = float((strategy_cfgs.get(name) or {}).get('weight', 1.0))
        fam = fam_of.get(name, 'OTHER')
        f = fams.setdefault(fam, {'bull': 0.0, 'bear': 0.0})
        if state == 'BULLISH':
            f['bull'] += w
            contributors.append(name)
        elif state == 'BEARISH':
            f['bear'] += w
            detractors.append(name)
        elif state == 'NEUTRAL':
            neutral.append(name)
        else:
            unavailable.append(name)
    bull_raw = sum(min(f['bull'], FAMILY_CAP) for f in fams.values())
    bear_raw = sum(min(f['bear'], FAMILY_CAP) for f in fams.values())
    denom = max(1.0, len(EVIDENCE_FAMILIES) * FAMILY_CAP)
    bullish_score = round(100.0 * bull_raw / denom)
    bearish_score = round(100.0 * bear_raw / denom)
    fams_bull = sum(1 for f in fams.values() if f['bull'] > 0)
    fams_bear = sum(1 for f in fams.values() if f['bear'] > 0)
    net = bullish_score - bearish_score
    conflicts = [f"{fam} split (bull {round(v['bull'],1)} vs bear {round(v['bear'],1)})"
                 for fam, v in fams.items() if v['bull'] > 0 and v['bear'] > 0]
    if bullish_score >= 55 and fams_bull >= STRONG_MIN_FAMILIES and net >= 30:
        state = 'BULLISH_STRONG'
    elif net >= 15 and fams_bull >= 2:
        state = 'BULLISH_CONDITIONAL'
    elif bearish_score >= 55 and fams_bear >= STRONG_MIN_FAMILIES and -net >= 30:
        state = 'BEARISH_STRONG'
    elif net <= -15 and fams_bear >= 2:
        state = 'BEARISH_CONDITIONAL'
    elif conflicts or (fams_bull >= 2 and fams_bear >= 2):
        state = 'MIXED'
    else:
        state = 'NEUTRAL'
    return {'bullish_score': bullish_score, 'bearish_score': bearish_score,
            'net_score': net, 'state': state,
            'independent_families_bullish': fams_bull,
            'independent_families_bearish': fams_bear,
            'family_contributions': {k: {'bull': round(min(v['bull'], FAMILY_CAP), 2),
                                         'bear': round(min(v['bear'], FAMILY_CAP), 2)}
                                     for k, v in fams.items()},
            'conflicts': conflicts, 'contributors': contributors,
            'detractors': detractors, 'neutral': neutral,
            'unavailable': unavailable,
            'weights_applied': True, 'family_cap': FAMILY_CAP,
            'strong_min_families': STRONG_MIN_FAMILIES}


def capability_audit() -> dict:
    """Startup capability truth (17.11): run every dispatch entry against a tiny
    synthetic OHLCV frame; an enabled indicator whose implementation is missing
    reports MISSING_IMPLEMENTATION — it must never masquerade as NEUTRAL."""
    import numpy as _np
    n = 80
    idx = pd.date_range('2025-01-01', periods=n, freq='D')
    base = 100 + _np.cumsum(_np.random.default_rng(7).normal(0, 1, n))
    df = pd.DataFrame({'open': base, 'high': base + 1, 'low': base - 1,
                       'close': base + 0.2, 'volume': _np.full(n, 1e6)}, index=idx)
    out = {}
    for name, fn in STRATEGY_FUNCTIONS.items():
        try:
            r = fn(df, (CONFIG.get('strategies', {}).get(name, {}) if CONFIG else {}))
            sig = str(r.get('signal', ''))
            err = str((r.get('details') or {}).get('error', ''))
            if sig == 'UNAVAILABLE' and ('has no attribute' in err or 'AttributeError' in err):
                out[name] = 'MISSING_IMPLEMENTATION'
            elif sig == 'UNAVAILABLE':
                out[name] = f'UNAVAILABLE:{err[:40]}'
            else:
                out[name] = 'AVAILABLE'
        except Exception as e:
            out[name] = f'FAILED:{str(e)[:40]}'
    out['_using_pandas_ta_shim'] = 'pandas_ta_shim' in getattr(ta, '__name__', str(ta))
    return out


# ── Strategy Dispatch Map ─────────────────────────────────────────────────────

STRATEGY_FUNCTIONS = {
    'rsi': _compute_rsi,
    'stochastic': _compute_stochastic,
    'macd': _compute_macd,
    'williams_r': _compute_williams_r,
    'ema': _compute_ema,
    'sma': _compute_sma,
    'vwap': _compute_vwap,
    'bollinger': _compute_bollinger,
    'keltner': _compute_keltner,
    'atr': _compute_atr,
    'fibonacci': _compute_fibonacci,
    'pivots_daily': _compute_pivots_daily,
    'pivots_weekly': _compute_pivots_weekly,
    'pivots_fibonacci': _compute_pivots_fibonacci,
    'volume_profile': _compute_volume_profile,
    'obv': _compute_obv,
    'volume_roc': _compute_volume_roc,
    'cmf': _compute_cmf,
    'adx': _compute_adx,
    'aroon': _compute_aroon,
}

BADGE_NAMES = {
    'rsi': 'RSI', 'stochastic': 'STOCH', 'macd': 'MACD',
    'williams_r': 'W%R', 'ema': 'EMA', 'sma': 'SMA',
    'vwap': 'VWAP', 'bollinger': 'BB', 'keltner': 'KC',
    'atr': 'ATR', 'fibonacci': 'FIB', 'pivots_daily': 'PVTD',
    'pivots_weekly': 'PVTW', 'pivots_fibonacci': 'PVTF',
    'volume_profile': 'VPRO', 'obv': 'OBV', 'volume_roc': 'VROL',
    'cmf': 'CMF', 'adx': 'ADX', 'aroon': 'ARN',
}


# ── Confluence Engine ─────────────────────────────────────────────────────────

def analyze_confluence(symbol: str, profile: str = 'swing') -> dict:
    """Main entry point. Compute confluence for symbol using the given profile.
    Returns full result dict including score, badges, levels, stop/target.
    Non-fatal: returns empty result on total failure."""
    try:
        cfg = CONFIG
        if not cfg:
            return {'ok': False, 'error': 'Config not loaded', 'symbol': symbol}

        profile_cfg = cfg.get('profiles', {}).get(profile, {})
        active_strategies = profile_cfg.get('active_strategies', list(STRATEGY_FUNCTIONS.keys()))
        strategy_cfgs = cfg.get('strategies', {})
        confluence_cfg = cfg.get('confluence', {})

        # Fetch OHLCV
        lookback = cfg.get('cache', {}).get('lookback_days', 90)
        df = _fetch_ohlcv(symbol, days=lookback)
        if df is None:
            return {'ok': False, 'error': f'No OHLCV data for {symbol}', 'symbol': symbol}

        # Run each active strategy
        signals = {}
        strategy_badges = []
        bearish_badges = []
        key_levels = {}
        stop_price = None
        target_price = None
        atr_value = None
        adx_regime = None
        entry_quality = None

        for strat_name in active_strategies:
            if strat_name not in STRATEGY_FUNCTIONS:
                continue
            strat_cfg = strategy_cfgs.get(strat_name, {})
            if not strat_cfg.get('enabled', True):
                continue

            try:
                result = STRATEGY_FUNCTIONS[strat_name](df, strat_cfg)
                signals[strat_name] = result

                if result['signal'] == 'BULLISH':
                    strategy_badges.append(BADGE_NAMES.get(strat_name, strat_name.upper()))
                elif result['signal'] == 'BEARISH':
                    bearish_badges.append(BADGE_NAMES.get(strat_name, strat_name.upper()))

                # Extract key outputs
                details = result.get('details', {})
                if strat_name == 'fibonacci':
                    key_levels['fibonacci'] = details.get('key_levels', {})
                elif strat_name in ('pivots_daily', 'pivots_weekly', 'pivots_fibonacci'):
                    key_levels[strat_name] = {k: details.get(k)
                                              for k in ('pp', 'r1', 'r2', 'r3', 's1', 's2', 's3')
                                              if details.get(k) is not None}
                elif strat_name == 'bollinger':
                    key_levels['bollinger'] = {k: details.get(k)
                                               for k in ('upper', 'middle', 'lower', 'bandwidth', 'squeeze')}
                elif strat_name == 'atr':
                    atr_value = details.get('atr')
                    current_price = float(df['close'].iloc[-1])
                    stop_mult = profile_cfg.get('stop_multiple', 1.0)
                    target_mult = profile_cfg.get('target_multiple', 2.0)
                    if atr_value:
                        stop_price = round(current_price - (stop_mult * atr_value), 2)
                        target_price = round(current_price + (target_mult * atr_value), 2)
                elif strat_name == 'adx':
                    adx_regime = details.get('regime')
                elif strat_name == 'rsi':
                    entry_quality = details.get('entry_quality')

            except Exception as e:
                logger.warning(f"Strategy {strat_name} failed for {symbol} (non-fatal): {e}")
                signals[strat_name] = _unavailable(e)

        # Score confluence
        bullish_count = sum(1 for s in signals.values() if s.get('signal') == 'BULLISH')
        bearish_count = sum(1 for s in signals.values() if s.get('signal') == 'BEARISH')
        neutral_count = sum(1 for s in signals.values() if s.get('signal') == 'NEUTRAL')

        strong_t = confluence_cfg.get('strong_threshold', 8)
        moderate_t = confluence_cfg.get('moderate_threshold', 5)
        weak_t = confluence_cfg.get('weak_threshold', 3)

        if bullish_count >= strong_t:
            tier = 'STRONG'
            pillar_score = confluence_cfg.get('score_strong', 10)
        elif bullish_count >= moderate_t:
            tier = 'MODERATE'
            pillar_score = confluence_cfg.get('score_moderate', 5)
        elif bullish_count >= weak_t:
            tier = 'WEAK'
            pillar_score = confluence_cfg.get('score_weak', 0)
        else:
            tier = 'NONE'
            pillar_score = 0

        return {
            'ok': True,
            'symbol': symbol,
            'profile': profile,
            'confluence_score': pillar_score,
            'confluence_tier': tier,
            'signals_bullish': bullish_count,
            'signals_bearish': bearish_count,
            'signals_neutral': neutral_count,
            'strategy_badges': strategy_badges,
            'bearish_badges': bearish_badges,
            'signals': signals,
            'key_levels': key_levels,
            'stop_price': stop_price,
            'target_price': target_price,
            'atr': atr_value,
            'adx_regime': adx_regime,
            'entry_quality': entry_quality,
            'confluence_v2': analyze_confluence_v2(signals, strategy_cfgs),
            'computed_at': datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"analyze_confluence failed for {symbol}: {e}")
        return {'ok': False, 'error': str(e), 'symbol': symbol}


# ── CLI Test Mode ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with PipelineRun("indicator_engine") as _run:
        import sys
        logging.basicConfig(level=logging.INFO)
        symbol = sys.argv[1] if len(sys.argv) > 1 else 'AMD'
        profile = sys.argv[2] if len(sys.argv) > 2 else 'scalp'
        print(f"\nRunning {profile} confluence analysis for {symbol}...")
        result = analyze_confluence(symbol, profile)
        if result.get('ok'):
            print(f"\nConfluence: {result['confluence_tier']} ({result['signals_bullish']} bullish, "
                  f"{result['signals_bearish']} bearish, {result['signals_neutral']} neutral)")
            print(f"Bullish badges: {result['strategy_badges']}")
            print(f"Bearish badges: {result['bearish_badges']}")
            print(f"Entry quality: {result['entry_quality']}")
            print(f"Stop: ${result['stop_price']} | Target: ${result['target_price']}")
            print(f"ADX regime: {result['adx_regime']}")
            if result.get('key_levels'):
                print(f"Key levels: {json.dumps(result['key_levels'], indent=2)}")
        else:
            print(f"FAILED: {result.get('error')}")

