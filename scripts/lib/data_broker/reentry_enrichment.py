# DEPRECATED 2026-08-06: No known consumers (only imported by orphaned reentry_scorecard).
# Scheduled for removal. See Wave B/C Data Broker compliance remediation.
"""Re-Entry Enrichment — Data Broker read models for the 8-stage scorecard.

Provides deterministic computed evidence for:
  S1 — Structure (undercut/reclaim, S/R flip, higher-low)
  S2 — VWAP (proximity, slope, anchored VWAP)
  S3 — Moving Averages (SMA 20/50/200 alignment)
  S4 — MACD (histogram direction, hidden bullish divergence)
  S5 — Fibonacci (retracement zone proximity)
  S6 — Volume & Tape (pullback volume, trigger volume, spread)
  S7 — Trigger Candle (bullish engulfing, hammer, dragonfly doji)
  S8 — Risk (R:R ratio, stop distance)

All data sourced through the Broker Waterfall: Schwab API > Alpaca > Yahoo > Moomoo > Finviz.
No LLM. No writes. Advisory only.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# ── helpers ──


def _scripts(path: str) -> None:
    s = str(PROJECT_ROOT / "scripts")
    if s not in sys.path:
        sys.path.insert(0, s)


def _f(value: Any) -> float | None:
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def _get_vwap_snapshot(db_query: Callable, symbol: str, max_age_h: int = 2) -> dict[str, Any] | None:
    """Read latest market_quote_snapshots for VWAP, volume, spread."""
    rows = db_query(
        """SELECT last_price, vwap, day_volume, spread, spread_pct,
                  quote_timestamp, provider, is_delayed
           FROM market_quote_snapshots
           WHERE upper(symbol) = upper(%s)
             AND created_at > NOW() - make_interval(hours => %s)
           ORDER BY created_at DESC
           LIMIT 1""",
        (symbol, max_age_h),
        fetch="one",
    )
    if rows:
        row = rows[0] if isinstance(rows, list) else rows
        return {
            "price": _f(row.get("last_price")),
            "vwap": _f(row.get("vwap")),
            "day_volume": row.get("day_volume"),
            "spread": _f(row.get("spread")),
            "spread_pct": _f(row.get("spread_pct")),
            "quote_timestamp": row.get("quote_timestamp"),
            "provider": row.get("provider"),
            "is_delayed": row.get("is_delayed"),
        }
    return None


def _get_vwap_slope(db_query: Callable, symbol: str, lookback_h: int = 4) -> dict[str, Any] | None:
    """Compare last two VWAP readings for slope."""
    rows = db_query(
        """SELECT vwap, created_at FROM market_quote_snapshots
           WHERE upper(symbol) = upper(%s) AND vwap IS NOT NULL
           ORDER BY created_at DESC LIMIT 2""",
        (symbol,),
    ) or []
    if len(rows) >= 2:
        v1 = _f(rows[0].get("vwap"))
        v2 = _f(rows[1].get("vwap"))
        if v1 is not None and v2 is not None and v2 > 0:
            slope_pct = ((v1 - v2) / v2) * 100
            direction = "rising" if slope_pct > 0.05 else ("falling" if slope_pct < -0.05 else "flat")
            return {"vwap_now": v1, "vwap_prior": v2, "slope_pct": round(slope_pct, 3), "direction": direction}
    # fallback: single reading, direction unknown
    if rows:
        return {"vwap_now": _f(rows[0].get("vwap")), "vwap_prior": None, "slope_pct": None, "direction": "unknown"}
    return None


def _get_intraday_bars(symbol: str, timeframe: str = "5Min", bars: int = 20) -> list[dict[str, Any]]:
    """Fetch intraday OHLCV bars via Schwab API with yfinance fallback."""
    _scripts("scripts")
    import datetime as _dt

    end = _dt.datetime.now(_dt.timezone.utc)
    if timeframe == "1Min":
        start = end - _dt.timedelta(minutes=bars + 10)
    else:
        start = end - _dt.timedelta(minutes=bars * 5 + 60)

    # --- Primary: Schwab API ---
    try:
        from schwab_transport import get_price_history
        result = get_price_history(symbol, start.isoformat(), end.isoformat(), timeframe=timeframe)
        if result:
            out = []
            for c in result:
                out.append({
                    "datetime": c.get("datetime"),
                    "open": _f(c.get("open")),
                    "high": _f(c.get("high")),
                    "low": _f(c.get("low")),
                    "close": _f(c.get("close")),
                    "volume": c.get("volume"),
                    "source": "schwab_api",
                })
            if out:
                return out[-bars:]
    except Exception:
        pass

    # --- Fallback: yfinance ---
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        if timeframe == "1Min":
            df = tk.history(period="1d", interval="1m")
        else:
            df = tk.history(period="1d", interval="5m")
        if not df.empty:
            out = []
            for idx, row in df.iterrows():
                out.append({
                    "datetime": str(idx),
                    "open": _f(row.get("Open")),
                    "high": _f(row.get("High")),
                    "low": _f(row.get("Low")),
                    "close": _f(row.get("Close")),
                    "volume": row.get("Volume"),
                    "source": "yfinance",
                })
            return out[-bars:]
    except Exception:
        pass

    return []


# ── Stage 2: VWAP ──


def get_vwap_evidence(db_query: Callable, symbol: str, price: float | None) -> dict[str, Any]:
    """VWAP proximity, slope, and anchored VWAP evidence."""
    snap = _get_vwap_snapshot(db_query, symbol)
    slope = _get_vwap_slope(db_query, symbol)

    vwap_val = snap.get("vwap") if snap else None
    vwap_dir = slope.get("direction") if slope else "unknown"
    vwap_slope_pct = slope.get("slope_pct") if slope else None

    distance_pct = None
    position = "unknown"
    if price is not None and vwap_val is not None and vwap_val > 0:
        distance_pct = ((price - vwap_val) / vwap_val) * 100
        if abs(distance_pct) <= 0.3:
            position = "at_vwap"
        elif distance_pct > 0:
            position = "above"
        else:
            position = "below"

    fired = False
    reason = "VWAP data unavailable"
    if vwap_val is not None and price is not None:
        dist_ok = distance_pct is not None and 0 <= distance_pct <= 6.0
        slope_ok = vwap_dir == "rising"
        if position == "at_vwap" and slope_ok:
            fired = True
            reason = f"Price at VWAP ({vwap_val:.2f}), VWAP rising"
        elif dist_ok and slope_ok:
            fired = True
            reason = f"Price {distance_pct:.1f}% above rising VWAP ({vwap_val:.2f})"
        elif dist_ok:
            fired = True
            reason = f"Price {distance_pct:.1f}% above VWAP ({vwap_val:.2f})"
        elif position == "below":
            reason = f"Price below VWAP ({vwap_val:.2f}) — wait for reclaim"
        else:
            reason = f"Price {distance_pct:.1f}% from VWAP ({vwap_val:.2f})"

    spread = snap.get("spread_pct") if snap else None
    spread_ok = spread is not None and spread < 1.0

    return {
        "fired": fired,
        "vwap_value": vwap_val,
        "distance_pct": round(distance_pct, 2) if distance_pct is not None else None,
        "position": position,
        "direction": vwap_dir,
        "slope_pct": round(vwap_slope_pct, 3) if vwap_slope_pct is not None else None,
        "spread_pct": round(spread, 3) if spread is not None else None,
        "spread_ok": spread_ok,
        "reason": reason,
        "data_available": vwap_val is not None,
        "source": f"market_quote_snapshots:{snap.get('provider', 'unknown')}" if snap else "none",
    }


# ── Stage 1: Structure ──


def get_structure_evidence(symbol: str, stop_price: float | None) -> dict[str, Any]:
    """Undercut & reclaim, S/R flip, higher-low structure from 5-min bars."""
    bars = _get_intraday_bars(symbol, timeframe="5Min", bars=20)

    undercut_reclaim = False
    sr_flip = False
    higher_low = False
    structural_support = None

    if len(bars) >= 10:
        closes = [b["close"] for b in bars if b["close"] is not None]
        lows = [b["low"] for b in bars if b["low"] is not None]
        highs = [b["high"] for b in bars if b["high"] is not None]
        volumes = [b.get("volume") for b in bars if b.get("volume") is not None]

        # --- Undercut & Reclaim ---
        if stop_price is not None and len(lows) >= 5:
            recent_lows = [l for l in lows[-5:] if l is not None]
            recent_closes = [c for c in closes[-5:] if c is not None]
            if recent_lows and recent_closes and len(recent_volumes := volumes[-5:]) >= 3:
                min_low = min(recent_lows)
                if min_low < stop_price and recent_closes[-1] > stop_price:
                    reclaim_vol = recent_volumes[-1] or 0
                    avg_vol = sum(v or 0 for v in recent_volumes[:-1]) / max(len(recent_volumes) - 1, 1)
                    if reclaim_vol >= avg_vol * 0.8:
                        undercut_reclaim = True
                        structural_support = stop_price

        # --- Higher-Low Structure ---
        if len(lows) >= 8:
            mid = len(lows) // 2
            first_half_lows = [l for l in lows[:mid] if l is not None]
            second_half_lows = [l for l in lows[mid:] if l is not None]
            if first_half_lows and second_half_lows:
                recent_swing_low = min(second_half_lows)
                prior_swing_low = min(first_half_lows)
                if recent_swing_low > prior_swing_low:
                    higher_low = True
                    if structural_support is None:
                        structural_support = recent_swing_low

        # --- S/R Flip ---
        if len(highs) >= 10:
            mid2 = len(highs) // 2
            resistance_zone = max(h for h in highs[:mid2] if h is not None)
            # Check if price stayed above this resistance zone in the second half
            second_closes = closes[mid2:]
            holds_above = all(c > resistance_zone * 0.99 for c in second_closes if c is not None)
            if holds_above and len(second_closes) >= 3:
                sr_flip = True
                if structural_support is None:
                    structural_support = resistance_zone

    structure_fired = undercut_reclaim or sr_flip or higher_low
    reasons = []
    if undercut_reclaim:
        reasons.append("undercut & reclaim detected")
    if sr_flip:
        reasons.append("S/R flip holding as support")
    if higher_low:
        reasons.append("higher-low structure intact")
    reason = "; ".join(reasons) if reasons else "no structural confirmation detected"

    return {
        "fired": structure_fired,
        "undercut_reclaim": undercut_reclaim,
        "sr_flip": sr_flip,
        "higher_low": higher_low,
        "structural_support": round(structural_support, 2) if structural_support is not None else None,
        "bars_available": len(bars),
        "reason": reason,
        "data_available": len(bars) >= 5,
        "source": f"intraday_bars:{bars[0].get('source', 'none')}" if bars else "none",
    }


# ── Stage 3: Moving Averages ──


def get_sma_evidence(indicators: dict[str, Any] | None) -> dict[str, Any]:
    """SMA 20/50/200 alignment from indicator snapshot."""
    if not indicators:
        return {
            "fired": False,
            "sma_20": None, "sma_50": None, "sma_200": None,
            "price_above_sma20": None,
            "sma20_above_sma50": None,
            "alignment": None,
            "reason": "No indicator data available",
            "data_available": False,
            "source": "none",
        }

    sma20 = _f(indicators.get("sma_20"))
    sma50 = _f(indicators.get("sma_50"))
    sma200 = _f(indicators.get("sma_200"))
    sma20_pct = _f(indicators.get("sma20_pct"))
    sma50_pct = _f(indicators.get("sma50_pct"))
    alignment = indicators.get("alignment")

    price_above_sma20 = sma20_pct is not None and sma20_pct > 0
    sma20_above_sma50 = sma20 is not None and sma50 is not None and sma20 > sma50
    sma50_above_sma200 = sma50 is not None and sma200 is not None and sma50 > sma200

    fired = price_above_sma20 and sma20_above_sma50
    if fired:
        reason = "Price above SMA 20 and SMA 20 above SMA 50 (bullish alignment)"
    elif price_above_sma20 and not sma20_above_sma50:
        reason = "Price above SMA 20 but SMA 20 below SMA 50 — wait for crossover"
    elif not price_above_sma20:
        reason = "Price below SMA 20 — trend not confirmed"
    else:
        reason = "SMA data insufficient for alignment check"

    return {
        "fired": fired,
        "sma_20": sma20,
        "sma_50": sma50,
        "sma_200": sma200,
        "sma20_pct": sma20_pct,
        "sma50_pct": sma50_pct,
        "sma200_pct": indicators.get("sma200_pct"),
        "price_above_sma20": price_above_sma20,
        "sma20_above_sma50": sma20_above_sma50,
        "sma50_above_sma200": sma50_above_sma200,
        "alignment": alignment,
        "reason": reason,
        "data_available": sma20 is not None and sma50 is not None,
        "source": "indicator_confluence_cache",
    }


# ── Stage 4: MACD ──


def get_macd_evidence(indicators: dict[str, Any] | None) -> dict[str, Any]:
    """MACD histogram direction and bullish divergence."""
    if not indicators:
        return {
            "fired": False,
            "macd_signal": None,
            "histogram_direction": None,
            "reason": "No indicator data available",
            "data_available": False,
            "source": "none",
        }

    macd_signal = indicators.get("macd_signal")
    hist_dir = indicators.get("macd_histogram_direction")

    fired = macd_signal == "BULLISH" or hist_dir == "expanding"
    if fired:
        reason = f"MACD {macd_signal} ({hist_dir or 'positive'}) — trend continuation signal"
    elif macd_signal == "BEARISH":
        reason = "MACD bearish — re-entry not supported"
    else:
        reason = "MACD neutral — no confirmation"

    return {
        "fired": fired,
        "macd_signal": macd_signal,
        "histogram_direction": hist_dir,
        "reason": reason,
        "data_available": macd_signal is not None,
        "source": "indicator_confluence_cache",
    }


# ── Stage 5: Fibonacci ──


def get_fib_evidence(indicators: dict[str, Any] | None) -> dict[str, Any]:
    """Fibonacci retracement zone proximity."""
    if not indicators:
        return {
            "fired": False,
            "nearest_level": None,
            "nearest_label": None,
            "nearest_pct": None,
            "at_level": False,
            "reason": "No indicator data available",
            "data_available": False,
            "source": "none",
        }

    # Fib data is parsed from full_result JSON inside indicator_confluence_cache
    # The indicator_snapshot normalizes some but may not include fib levels directly
    # We check what we can from the snapshot; the scorecard can also call indicator_engine directly
    rsi = _f(indicators.get("rsi"))
    # Fib is not directly in the normalized snapshot — use rsi + price context as proxy
    # The actual Fib computation lives in indicator_engine._compute_fibonacci
    # For now we report as not directly available from snapshot normalization
    return {
        "fired": False,
        "nearest_level": None,
        "nearest_label": None,
        "nearest_pct": None,
        "at_level": False,
        "reason": "Fib levels not available in indicator snapshot — requires direct indicator_engine call",
        "data_available": False,
        "source": "indicator_confluence_cache (fib not normalized)",
    }


# ── Stage 6: Volume & Tape ──


def get_volume_evidence(db_query: Callable, symbol: str) -> dict[str, Any]:
    """Volume declining on pullback, expanding on trigger, spread check."""
    bars = _get_intraday_bars(symbol, timeframe="5Min", bars=15)
    snap = _get_vwap_snapshot(db_query, symbol)

    volume_declining = False
    trigger_volume_ok = False

    if len(bars) >= 8:
        volumes = [b.get("volume") for b in bars if b.get("volume") is not None]
        if len(volumes) >= 8:
            # First half vs second half for declining check
            first_4 = volumes[:4]
            second_4 = volumes[4:8]
            avg_first = sum(first_4) / 4 if first_4 else 0
            avg_second = sum(second_4) / 4 if second_4 else 0
            volume_declining = avg_second < avg_first * 0.9

        # Trigger volume check: last candle vs average of prior 5
        if len(volumes) >= 6:
            last_vol = volumes[-1]
            avg_prior_5 = sum(volumes[-6:-1]) / 5 if len(volumes[-6:-1]) == 5 else 0
            trigger_volume_ok = last_vol is not None and avg_prior_5 > 0 and last_vol >= avg_prior_5

    spread = snap.get("spread_pct") if snap else None
    spread_ok = spread is not None and spread < 1.0

    fired = volume_declining and trigger_volume_ok and spread_ok
    reasons = []
    if volume_declining:
        reasons.append("pullback volume declining")
    if trigger_volume_ok:
        reasons.append("trigger volume above average")
    if spread_ok:
        reasons.append(f"spread tight ({spread:.2f}%)")
    reason = "; ".join(reasons) if reasons else "volume/tape evidence insufficient"

    return {
        "fired": fired,
        "volume_declining": volume_declining,
        "trigger_volume_ok": trigger_volume_ok,
        "spread_pct": round(spread, 3) if spread is not None else None,
        "spread_ok": spread_ok,
        "bars_available": len(bars),
        "reason": reason,
        "data_available": len(bars) >= 6 and snap is not None,
        "source": f"intraday_bars+market_quote_snapshots:{snap.get('provider', 'unknown')}" if snap else f"intraday_bars:{bars[0].get('source', 'none')}" if bars else "none",
    }


# ── Stage 7: Trigger Candle ──


def _detect_hammer(c: dict) -> bool:
    """Hammer: small body in upper portion, long lower wick >= 2x body."""
    o, h, l, cl = c.get("open"), c.get("high"), c.get("low"), c.get("close")
    if any(v is None for v in (o, h, l, cl)):
        return False
    body = abs(cl - o)
    if body == 0:
        return False
    lower_wick = min(o, cl) - l
    upper_wick = h - max(o, cl)
    return lower_wick >= body * 2 and upper_wick <= body * 0.5


def _detect_engulfing(prev: dict, curr: dict) -> bool:
    """Bullish engulfing: prev red, curr green and body engulfs prev body."""
    po, pc = prev.get("open"), prev.get("close")
    co, cc = curr.get("open"), curr.get("close")
    if any(v is None for v in (po, pc, co, cc)):
        return False
    prev_red = pc < po
    curr_green = cc > co
    if not (prev_red and curr_green):
        return False
    return co <= pc and cc >= po


def _detect_dragonfly(c: dict) -> bool:
    """Dragonfly doji: open ~= close, long lower wick, minimal upper wick."""
    o, h, l, cl = c.get("open"), c.get("high"), c.get("low"), c.get("close")
    if any(v is None for v in (o, h, l, cl)):
        return False
    body = abs(cl - o)
    candle_range = h - l
    if candle_range == 0:
        return False
    lower_wick = min(o, cl) - l
    return body <= candle_range * 0.15 and lower_wick >= candle_range * 0.6


def get_trigger_evidence(symbol: str) -> dict[str, Any]:
    """Trigger candle patterns from 1-min bars."""
    bars = _get_intraday_bars(symbol, timeframe="1Min", bars=10)

    hammer_detected = False
    engulfing_detected = False
    dragonfly_detected = False

    if len(bars) >= 2:
        # Check last candle
        last = bars[-1]
        hammer_detected = _detect_hammer(last)
        dragonfly_detected = _detect_dragonfly(last)
        engulfing_detected = _detect_engulfing(bars[-2], last)

    fired = hammer_detected or engulfing_detected or dragonfly_detected
    reasons = []
    if hammer_detected:
        reasons.append("hammer")
    if engulfing_detected:
        reasons.append("bullish engulfing")
    if dragonfly_detected:
        reasons.append("dragonfly doji")
    reason = "trigger: " + ", ".join(reasons) if reasons else "no trigger candle pattern detected"

    return {
        "fired": fired,
        "hammer": hammer_detected,
        "engulfing": engulfing_detected,
        "dragonfly": dragonfly_detected,
        "bars_available": len(bars),
        "reason": reason,
        "data_available": len(bars) >= 2,
        "source": f"intraday_1min:{bars[0].get('source', 'none')}" if bars else "none",
    }


# ── Stage 8: Risk ──


def get_risk_evidence(
    symbol: str,
    price: float | None,
    stop_price: float | None,
    target_price: float | None,
    entry_low: float | None,
    resistance: float | None,
    attempt_number: int = 0,
) -> dict[str, Any]:
    """R:R ratio >= 2:1 check. Stop must be structurally different from prior stop."""
    rr_ratio = None
    arrived_rr = None
    stop_ok = False

    # Check R:R
    if price is not None and stop_price is not None and target_price is not None and stop_price > 0 and price > 0:
        risk = price - stop_price
        reward = target_price - price
        if risk > 0:
            rr_ratio = round(reward / risk, 2)

    # Check R:R using resistance as target fallback
    if rr_ratio is None and price is not None and stop_price is not None and resistance is not None:
        if price > 0 and stop_price > 0:
            risk = price - stop_price
            reward = resistance - price
            if risk > 0:
                arrived_rr = round(reward / risk, 2)

    rr_ok = (rr_ratio is not None and rr_ratio >= 2.0) or (arrived_rr is not None and arrived_rr >= 2.0)

    # Stop quality: structurally different if entry zone provides a new (lower) stop
    if entry_low is not None and stop_price is not None:
        stop_ok = stop_price < entry_low  # stop is below entry zone = structurally valid

    attempt_ok = attempt_number < 3  # max 2 re-entries

    fired = rr_ok and stop_ok and attempt_ok

    reasons = []
    if rr_ok and rr_ratio is not None:
        reasons.append(f"R:R {rr_ratio:.1f}:1 >= 2:1")
    elif rr_ok and arrived_rr is not None:
        reasons.append(f"R:R (resistance) {arrived_rr:.1f}:1 >= 2:1")
    elif rr_ratio is not None:
        reasons.append(f"R:R {rr_ratio:.1f}:1 < 2:1 threshold")
    if stop_ok:
        reasons.append("stop structurally below entry zone")
    else:
        reasons.append("stop not validated structurally")
    if not attempt_ok:
        reasons.append(f"attempt #{attempt_number} exceeds max 2 re-entries")
    reason = "; ".join(reasons) if reasons else "risk criteria not met"

    return {
        "fired": fired,
        "rr_ratio": rr_ratio,
        "arrived_rr": arrived_rr,
        "rr_ok": rr_ok,
        "stop_ok": stop_ok,
        "attempt_number": attempt_number,
        "attempt_ok": attempt_ok,
        "reason": reason,
        "data_available": price is not None and stop_price is not None and (target_price is not None or resistance is not None),
        "source": "watchlist_entry_plans + resistance_cache",
    }
