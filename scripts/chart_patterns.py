#!/usr/bin/env python3
"""chart_patterns.py — deterministic classical chart-pattern engine (Section 17.4-17.6).

Pure OHLCV geometry. NO LLM, NO image description, NO network, NO DB. Pivot-based
detection with ATR/percentage-normalized tolerances so a $6 stock and a $600 stock
use the same relative rules. Confirmed signals use CLOSED bars only — the current
(possibly live) bar never confirms anything; callers pass closed bars.

Every detection carries exactly one lifecycle state:
    FORMING              geometry incomplete / current-structure developing
    AWAITING_CONFIRMATION geometry complete, trigger not yet closed-broken
    CONFIRMED            a CLOSED bar broke the trigger
    RETESTING            confirmed, price back within tolerance of the boundary
    FAILED               confirmed then closed back through invalidation
    EXPIRED              geometry older than max age without confirmation

Quality is deterministic (geometry/symmetry/volume/duration/boundary components,
0-100). No model-authored confidence anywhere.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

ENGINE_VERSION = "1.0.0"

# ── tolerances (ATR-normalized / fractional) ─────────────────────────────────
PIVOT_MIN_REVERSAL_ATR = 1.2     # zigzag reversal threshold
EQ_TOL_ATR = 0.9                 # "equal" peaks/troughs tolerance
SHOULDER_TOL_ATR = 1.3           # shoulder height match
HEAD_MIN_ABOVE_ATR = 1.0         # head must exceed shoulders by this
NECKLINE_MAX_SLOPE = 0.35        # |slope| in ATR per bar-gap units
RETEST_TOL_ATR = 0.6
MAX_PATTERN_AGE_BARS = 90
FLAG_POLE_MIN_ATR = 3.0
FLAG_MAX_RETRACE = 0.5
MIN_QUALITY_PRIMARY = 55         # below → audit-only, never a primary pill


@dataclass
class Pivot:
    idx: int
    price: float
    kind: str            # 'H' | 'L'
    prominence_atr: float
    ts: str = ""


def _atr(bars: list[dict], period: int = 14) -> float:
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    tail = trs[-period:]
    return sum(tail) / len(tail)


def find_pivots(bars: list[dict], reversal_atr: float = PIVOT_MIN_REVERSAL_ATR) -> list[Pivot]:
    """Zigzag pivots on closed bars: a pivot forms when price reverses by
    >= reversal_atr * ATR from the running extreme. No lookahead: a pivot at
    bar i is only knowable once the reversal completes at a LATER bar — callers
    treating the most recent leg as tentative get that via the returned last
    running extreme being excluded."""
    if len(bars) < 10:
        return []
    atr = _atr(bars)
    if atr <= 0:
        return []
    piv: list[Pivot] = []
    thr = reversal_atr * atr
    # CLOSE-based reversal detection: a single wide bar's own high-low range must
    # not flip the zigzag (the first implementation did exactly that — every bar
    # became a pivot). Highs/lows only refine the recorded extreme price.
    direction = 0    # +1 tracking a rising leg (next pivot is a High), -1 falling
    ext_i = 0
    ext_close = bars[0]["close"]
    lo_i, lo_c = 0, bars[0]["close"]
    hi_i, hi_c = 0, bars[0]["close"]
    for i, b in enumerate(bars):
        c = b["close"]
        if direction == 0:
            # bootstrap: fixed min/max anchors (a trailing anchor never accumulates)
            if c > hi_c:
                hi_i, hi_c = i, c
            if c < lo_c:
                lo_i, lo_c = i, c
            if hi_c - lo_c >= thr:
                direction = 1 if hi_i > lo_i else -1
                ext_i, ext_close = (hi_i, hi_c) if direction == 1 else (lo_i, lo_c)
            continue
        if direction == 1:
            if c > ext_close:
                ext_i, ext_close = i, c
            elif ext_close - c >= thr:
                hi_i = max(range(max(0, ext_i - 1), min(len(bars), ext_i + 2)),
                           key=lambda j: bars[j]["high"])
                piv.append(Pivot(hi_i, round(bars[hi_i]["high"], 4), "H",
                                 round((ext_close - c) / atr, 2), str(bars[hi_i].get("ts", ""))))
                direction, ext_i, ext_close = -1, i, c
        else:
            if c < ext_close:
                ext_i, ext_close = i, c
            elif c - ext_close >= thr:
                lo_i = max(range(max(0, ext_i - 1), min(len(bars), ext_i + 2)),
                           key=lambda j: -bars[j]["low"])
                piv.append(Pivot(lo_i, round(bars[lo_i]["low"], 4), "L",
                                 round((c - ext_close) / atr, 2), str(bars[lo_i].get("ts", ""))))
                direction, ext_i, ext_close = 1, i, c
    # enforce alternation (safety)
    out: list[Pivot] = []
    for p in piv:
        if out and out[-1].kind == p.kind:
            keep = (p if ((p.kind == "H" and p.price >= out[-1].price)
                          or (p.kind == "L" and p.price <= out[-1].price)) else out[-1])
            out[-1] = keep
        else:
            out.append(p)
    return out


# ── shared result assembly ───────────────────────────────────────────────────
def _mk(pattern, direction, bars, atr, *, state, trigger, invalidation, target,
        quality: dict, points: dict, started_idx: int, boundary_note: str = "") -> dict:
    last_close = bars[-1]["close"]
    q_w = {"geometry": 0.3, "symmetry": 0.2, "volume_confirmation": 0.15,
           "duration": 0.15, "boundary_quality": 0.2}
    qscore = round(sum(quality.get(k, 50) * w for k, w in q_w.items()))
    dist = round(100.0 * (trigger - last_close) / last_close, 2) if trigger else None
    return {
        "pattern": pattern, "direction": direction, "state": state,
        "engine_version": ENGINE_VERSION,
        "trigger": round(trigger, 2) if trigger is not None else None,
        "trigger_rule": (f"close {'below' if direction == 'BEARISH' else 'above'} "
                         f"{round(trigger, 2)}" if trigger is not None else None),
        "invalidation": round(invalidation, 2) if invalidation is not None else None,
        "measured_target": round(target, 2) if target is not None else None,
        "distance_to_trigger_pct": dist,
        "quality_score": qscore, "quality_components": {k: round(v) for k, v in quality.items()},
        "points": {k: (round(v, 2) if isinstance(v, (int, float)) else v) for k, v in points.items()},
        "boundary_note": boundary_note,
        "started_at_bar": started_idx, "bars_used": len(bars),
        "atr_used": round(atr, 4),
        "primary_eligible": qscore >= MIN_QUALITY_PRIMARY,
    }


def _confirm_state(bars, trigger, direction, invalidation, atr, geometry_end_idx) -> str:
    """Lifecycle from CLOSED bars after geometry completion. No lookahead: only
    bars after the geometry end can confirm."""
    post = bars[geometry_end_idx + 1:]
    if not post:
        return "AWAITING_CONFIRMATION"
    confirmed_i = None
    for j, b in enumerate(post):
        c = b["close"]
        if direction == "BEARISH" and c < trigger:
            confirmed_i = j
            break
        if direction == "BULLISH" and c > trigger:
            confirmed_i = j
            break
    if confirmed_i is None:
        if len(post) > MAX_PATTERN_AGE_BARS:
            return "EXPIRED"
        return "AWAITING_CONFIRMATION"
    after = post[confirmed_i + 1:]
    for b in after:
        c = b["close"]
        if direction == "BEARISH" and invalidation is not None and c > invalidation:
            return "FAILED"
        if direction == "BULLISH" and invalidation is not None and c < invalidation:
            return "FAILED"
    if after:
        last = after[-1]["close"]
        if abs(last - trigger) <= RETEST_TOL_ATR * atr:
            return "RETESTING"
    return "CONFIRMED"


def _vol_conf(bars, idx) -> float:
    """Breakout-bar volume vs trailing 20-bar average → 0-100."""
    if idx is None or idx < 1 or idx >= len(bars):
        return 50.0
    vols = [b.get("volume") or 0 for b in bars[max(0, idx - 20):idx]]
    avg = (sum(vols) / len(vols)) if vols else 0
    v = bars[idx].get("volume") or 0
    if avg <= 0:
        return 50.0
    r = v / avg
    return max(0.0, min(100.0, 50.0 * r))


# ── detectors ────────────────────────────────────────────────────────────────
def detect_head_and_shoulders(bars: list[dict], pivots: list[Pivot], atr: float) -> list[dict]:
    """H&S (BEARISH) and inverse (BULLISH) on 5 alternating pivots."""
    out = []
    for inv in (False, True):
        want = ["H", "L", "H", "L", "H"] if not inv else ["L", "H", "L", "H", "L"]
        for i in range(len(pivots) - 4):
            w = pivots[i:i + 5]
            if [p.kind for p in w] != want:
                continue
            ls, n1, head, n2, rs = w
            sign = -1.0 if inv else 1.0
            if sign * (head.price - ls.price) < HEAD_MIN_ABOVE_ATR * atr:
                continue
            if sign * (head.price - rs.price) < HEAD_MIN_ABOVE_ATR * atr:
                continue
            if abs(ls.price - rs.price) > SHOULDER_TOL_ATR * atr:
                continue
            gap = max(1, n2.idx - n1.idx)
            neck_slope = (n2.price - n1.price) / gap
            if abs(neck_slope) > NECKLINE_MAX_SLOPE * atr:
                continue
            neck_at_end = n2.price + neck_slope * (len(bars) - 1 - n2.idx)
            depth = abs(head.price - (n1.price + n2.price) / 2)
            direction = "BULLISH" if inv else "BEARISH"
            trigger = neck_at_end
            invalidation = rs.price
            target = neck_at_end + (depth if inv else -depth)
            sym_t = 1 - min(1, abs((head.idx - ls.idx) - (rs.idx - head.idx)) / max(1, rs.idx - ls.idx))
            sym_p = 1 - min(1, abs(ls.price - rs.price) / max(atr, 1e-9) / SHOULDER_TOL_ATR)
            state = _confirm_state(bars, trigger, direction, invalidation, atr, rs.idx)
            brk = next((rs.idx + 1 + j for j, b in enumerate(bars[rs.idx + 1:])
                        if (b["close"] > trigger if inv else b["close"] < trigger)), None)
            quality = {"geometry": 60 + 40 * sym_p, "symmetry": 100 * (sym_t * 0.5 + sym_p * 0.5),
                       "volume_confirmation": _vol_conf(bars, brk),
                       "duration": min(100, 100 * (rs.idx - ls.idx) / 40),
                       "boundary_quality": 100 - min(100, abs(neck_slope) / (NECKLINE_MAX_SLOPE * atr) * 100)}
            out.append(_mk("INVERSE_HEAD_AND_SHOULDERS" if inv else "HEAD_AND_SHOULDERS",
                           direction, bars, atr, state=state, trigger=trigger,
                           invalidation=invalidation, target=target, quality=quality,
                           points={"left_shoulder": ls.price, "head": head.price,
                                   "right_shoulder": rs.price, "neckline": round(neck_at_end, 2)},
                           started_idx=ls.idx,
                           boundary_note=f"neckline slope {neck_slope:+.3f}/bar"))
    return out


def detect_double_extreme(bars: list[dict], pivots: list[Pivot], atr: float) -> list[dict]:
    """Double/triple tops (BEARISH) and bottoms (BULLISH). Documented tolerances:
    extremes within EQ_TOL_ATR; middle pivot depth >= PIVOT reversal (implicit)."""
    out = []
    for kind, direction, name2, name3 in (("H", "BEARISH", "DOUBLE_TOP", "TRIPLE_TOP"),
                                          ("L", "BULLISH", "DOUBLE_BOTTOM", "TRIPLE_BOTTOM")):
        ext = [p for p in pivots if p.kind == kind]
        mids = [p for p in pivots if p.kind != kind]
        for i in range(len(ext) - 1):
            a, b = ext[i], ext[i + 1]
            if abs(a.price - b.price) > EQ_TOL_ATR * atr:
                continue
            mid = next((m for m in mids if a.idx < m.idx < b.idx), None)
            if mid is None:
                continue
            depth = abs(((a.price + b.price) / 2) - mid.price)
            if depth < PIVOT_MIN_REVERSAL_ATR * atr:
                continue
            third = ext[i + 2] if i + 2 < len(ext) and abs(ext[i + 2].price - a.price) <= EQ_TOL_ATR * atr else None
            trigger = mid.price
            invalidation = max(a.price, b.price) if kind == "H" else min(a.price, b.price)
            target = trigger + (-depth if kind == "H" else depth)
            end_idx = (third or b).idx
            state = _confirm_state(bars, trigger, direction, invalidation, atr, end_idx)
            brk = next((end_idx + 1 + j for j, bb in enumerate(bars[end_idx + 1:])
                        if (bb["close"] < trigger if kind == "H" else bb["close"] > trigger)), None)
            match = 1 - abs(a.price - b.price) / max(EQ_TOL_ATR * atr, 1e-9)
            quality = {"geometry": 55 + 45 * match, "symmetry": 100 * match,
                       "volume_confirmation": _vol_conf(bars, brk),
                       "duration": min(100, 100 * (b.idx - a.idx) / 25),
                       "boundary_quality": min(100, 100 * depth / (3 * atr))}
            out.append(_mk(name3 if third else name2, direction, bars, atr, state=state,
                           trigger=trigger, invalidation=invalidation, target=target,
                           quality=quality,
                           points={"first": a.price, "second": b.price,
                                   **({"third": third.price} if third else {}),
                                   "middle": mid.price},
                           started_idx=a.idx))
    return out


def detect_flag(bars: list[dict], pivots: list[Pivot], atr: float) -> list[dict]:
    """Bull/bear flags & pennants: strong pole then a short counter-drift
    consolidation retracing <= FLAG_MAX_RETRACE of the pole."""
    out = []
    n = len(bars)
    if n < 25:
        return out
    for pole_len in (8, 13, 21):
        if n < pole_len + 6:
            continue
        cons = bars[-6:]
        pole = bars[-(pole_len + 6):-6]
        move = pole[-1]["close"] - pole[0]["close"]
        if abs(move) < FLAG_POLE_MIN_ATR * atr:
            continue
        direction = "BULLISH" if move > 0 else "BEARISH"
        c_hi = max(b["high"] for b in cons)
        c_lo = min(b["low"] for b in cons)
        retrace = ((pole[-1]["close"] - cons[-1]["close"]) / move) if move else 0
        if retrace > FLAG_MAX_RETRACE or retrace < -0.15:
            continue
        width = c_hi - c_lo
        if width > 2.5 * atr:
            continue
        trigger = c_hi if direction == "BULLISH" else c_lo
        invalidation = c_lo if direction == "BULLISH" else c_hi
        target = trigger + (abs(move) if direction == "BULLISH" else -abs(move))
        state = "AWAITING_CONFIRMATION"
        last = bars[-1]["close"]
        if (direction == "BULLISH" and last > trigger) or (direction == "BEARISH" and last < trigger):
            state = "CONFIRMED"
        name = ("BULL_FLAG" if direction == "BULLISH" else "BEAR_FLAG") if width > 1.2 * atr else \
               ("BULLISH_PENNANT" if direction == "BULLISH" else "BEARISH_PENNANT")
        quality = {"geometry": min(100, 100 * abs(move) / (5 * atr)),
                   "symmetry": 100 - min(100, 100 * abs(retrace) / FLAG_MAX_RETRACE),
                   "volume_confirmation": _vol_conf(bars, n - 1 if state == "CONFIRMED" else None),
                   "duration": 70, "boundary_quality": 100 - min(100, 100 * width / (2.5 * atr))}
        out.append(_mk(name, direction, bars, atr, state=state, trigger=trigger,
                       invalidation=invalidation, target=target, quality=quality,
                       points={"pole_start": pole[0]["close"], "pole_end": pole[-1]["close"],
                               "flag_high": c_hi, "flag_low": c_lo},
                       started_idx=n - pole_len - 6))
        break
    return out


def _fit(vals: list[tuple[int, float]]):
    n = len(vals)
    if n < 2:
        return 0.0, (vals[0][1] if vals else 0.0)
    sx = sum(i for i, _ in vals); sy = sum(v for _, v in vals)
    sxx = sum(i * i for i, _ in vals); sxy = sum(i * v for i, v in vals)
    den = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / den if den else 0.0
    return slope, (sy - slope * sx) / n


def detect_triangle_wedge(bars: list[dict], pivots: list[Pivot], atr: float) -> list[dict]:
    """Ascending/descending/symmetrical triangles, rising/falling wedges,
    rectangles — boundary regression on the last 5+ pivots."""
    out = []
    recent = pivots[-6:]
    highs = [(p.idx, p.price) for p in recent if p.kind == "H"]
    lows = [(p.idx, p.price) for p in recent if p.kind == "L"]
    if len(highs) < 2 or len(lows) < 2:
        return out
    sh, ih = _fit(highs)
    sl, il = _fit(lows)
    flat = 0.08 * atr        # per-bar slope considered flat
    end = len(bars) - 1
    top_now = sh * end + ih
    bot_now = sl * end + il
    if top_now <= bot_now:
        return out
    name = direction = None
    if abs(sh) <= flat and sl > flat:
        name, direction = "ASCENDING_TRIANGLE", "BULLISH"
    elif sh < -flat and abs(sl) <= flat:
        name, direction = "DESCENDING_TRIANGLE", "BEARISH"
    elif sh < -flat and sl > flat:
        name, direction = "SYMMETRICAL_TRIANGLE", "NEUTRAL"
    elif sh > flat and sl > flat and sl > sh:
        name, direction = "RISING_WEDGE", "BEARISH"
    elif sh < -flat and sl < -flat and sh < sl:
        name, direction = "FALLING_WEDGE", "BULLISH"
    elif abs(sh) <= flat and abs(sl) <= flat and (top_now - bot_now) > 1.5 * atr:
        name, direction = "RECTANGLE", "NEUTRAL"
    if not name:
        return out
    trigger = top_now if direction != "BEARISH" else bot_now
    invalidation = bot_now if direction != "BEARISH" else top_now
    height = abs((highs[0][1]) - (lows[0][1]))
    target = trigger + (height if direction != "BEARISH" else -height)
    last = bars[-1]["close"]
    state = "FORMING"
    if direction == "BULLISH" and last > trigger:
        state = "CONFIRMED"
    elif direction == "BEARISH" and last < trigger:
        state = "CONFIRMED"
    elif direction == "NEUTRAL":
        if last > top_now:
            state, direction, trigger, invalidation = "CONFIRMED", "BULLISH", top_now, bot_now
            target = trigger + height
        elif last < bot_now:
            state, direction, trigger, invalidation = "CONFIRMED", "BEARISH", bot_now, top_now
            target = trigger - height
        else:
            state = "FORMING"
    touches = len(highs) + len(lows)
    quality = {"geometry": min(100, 25 * touches),
               "symmetry": 100 - min(100, 200 * abs(abs(sh) - abs(sl)) / max(flat, 1e-9) / 10),
               "volume_confirmation": _vol_conf(bars, end if state == "CONFIRMED" else None),
               "duration": min(100, 100 * (end - recent[0].idx) / 40),
               "boundary_quality": min(100, 25 * touches)}
    out.append(_mk(name, direction, bars, atr, state=state, trigger=trigger,
                   invalidation=invalidation, target=target, quality=quality,
                   points={"upper_now": round(top_now, 2), "lower_now": round(bot_now, 2),
                           "upper_slope": round(sh, 4), "lower_slope": round(sl, 4)},
                   started_idx=recent[0].idx))
    return out


def detect_cup_and_handle(bars: list[dict], pivots: list[Pivot], atr: float) -> list[dict]:
    n = len(bars)
    if n < 40:
        return []
    closes = [b["close"] for b in bars]
    rim_l_idx = max(range(n // 3), key=lambda i: closes[i])
    rim_l = closes[rim_l_idx]
    bottom_idx = min(range(rim_l_idx, n - 8), key=lambda i: closes[i], default=None)
    if bottom_idx is None:
        return []
    depth = rim_l - closes[bottom_idx]
    if depth < 3 * atr:
        return []
    recover_idx = next((i for i in range(bottom_idx, n) if closes[i] >= rim_l - EQ_TOL_ATR * atr), None)
    if recover_idx is None:
        return []
    handle = closes[recover_idx:]
    if len(handle) < 3:
        return []
    h_low = min(handle)
    if rim_l - h_low > depth / 3 or rim_l - h_low < 0.2 * atr:
        return []
    left_leg, right_leg = bottom_idx - rim_l_idx, recover_idx - bottom_idx
    sym = 1 - min(1, abs(left_leg - right_leg) / max(1, left_leg + right_leg))
    trigger = rim_l
    state = "AWAITING_CONFIRMATION" if closes[-1] <= trigger else "CONFIRMED"
    quality = {"geometry": 50 + 50 * sym, "symmetry": 100 * sym,
               "volume_confirmation": _vol_conf(bars, n - 1 if state == "CONFIRMED" else None),
               "duration": min(100, 100 * (n - rim_l_idx) / 60),
               "boundary_quality": min(100, 100 * depth / (6 * atr))}
    return [_mk("CUP_AND_HANDLE", "BULLISH", bars, atr, state=state, trigger=trigger,
                invalidation=h_low, target=rim_l + depth, quality=quality,
                points={"rim": rim_l, "bottom": closes[bottom_idx], "handle_low": h_low},
                started_idx=rim_l_idx)]


def detect_candles(bars: list[dict], atr: float) -> list[dict]:
    """Last-closed-bar candle/bar structures (17.4 D). Compact contract: name,
    direction, always state=CONFIRMED (a closed candle IS the event) but never
    primary_eligible on its own quality."""
    out = []
    if len(bars) < 3:
        return out
    a, b, c = bars[-3], bars[-2], bars[-1]

    def body(x):
        return abs(x["close"] - x["open"])

    def rng(x):
        return max(x["high"] - x["low"], 1e-9)

    def add(name, direction, note):
        out.append({"pattern": name, "direction": direction, "state": "CONFIRMED",
                    "candle": True, "note": note, "quality_score": 45,
                    "primary_eligible": False, "engine_version": ENGINE_VERSION})
    # engulfing
    if body(c) > body(b) and c["close"] > c["open"] and b["close"] < b["open"] \
            and c["close"] >= b["open"] and c["open"] <= b["close"]:
        add("BULLISH_ENGULFING", "BULLISH", "closed body engulfs prior down bar")
    if body(c) > body(b) and c["close"] < c["open"] and b["close"] > b["open"] \
            and c["open"] >= b["close"] and c["close"] <= b["open"]:
        add("BEARISH_ENGULFING", "BEARISH", "closed body engulfs prior up bar")
    # hammer family (position-aware naming only, not trend-aware)
    low_wick = min(c["open"], c["close"]) - c["low"]
    up_wick = c["high"] - max(c["open"], c["close"])
    if body(c) < 0.35 * rng(c) and low_wick > 2 * body(c) and up_wick < body(c):
        add("HAMMER", "BULLISH", "long lower wick, small body")
    if body(c) < 0.35 * rng(c) and up_wick > 2 * body(c) and low_wick < body(c):
        add("SHOOTING_STAR", "BEARISH", "long upper wick, small body")
    if body(c) < 0.1 * rng(c):
        add("DOJI", "NEUTRAL", "open≈close")
    # inside / outside
    if c["high"] < b["high"] and c["low"] > b["low"]:
        add("INSIDE_BAR", "NEUTRAL", "range inside prior bar")
    if c["high"] > b["high"] and c["low"] < b["low"]:
        add("OUTSIDE_BAR", "NEUTRAL", "range engulfs prior bar")
    # morning/evening star (3-bar)
    if a["close"] < a["open"] and body(b) < 0.4 * body(a) and c["close"] > c["open"] \
            and c["close"] > (a["open"] + a["close"]) / 2:
        add("MORNING_STAR", "BULLISH", "3-bar reversal up")
    if a["close"] > a["open"] and body(b) < 0.4 * body(a) and c["close"] < c["open"] \
            and c["close"] < (a["open"] + a["close"]) / 2:
        add("EVENING_STAR", "BEARISH", "3-bar reversal down")
    return out


def detect_all(bars: list[dict]) -> dict:
    """Full pass over CLOSED bars. Returns {patterns, candles, pivots_used, atr}.
    Low-quality detections are retained (audit) with primary_eligible=False."""
    if not bars or len(bars) < 15:
        return {"patterns": [], "candles": [], "pivots_used": 0, "atr": None,
                "note": "insufficient closed bars"}
    atr = _atr(bars)
    if atr <= 0:
        return {"patterns": [], "candles": [], "pivots_used": 0, "atr": 0.0,
                "note": "zero ATR"}
    piv = find_pivots(bars)
    pats: list[dict] = []
    pats += detect_head_and_shoulders(bars, piv, atr)
    pats += detect_double_extreme(bars, piv, atr)
    pats += detect_flag(bars, piv, atr)
    pats += detect_triangle_wedge(bars, piv, atr)
    pats += detect_cup_and_handle(bars, piv, atr)
    # rank: confirmed first, then quality
    order = {"CONFIRMED": 0, "RETESTING": 1, "AWAITING_CONFIRMATION": 2,
             "FORMING": 3, "FAILED": 4, "EXPIRED": 5}
    pats.sort(key=lambda p: (order.get(p["state"], 9), -p["quality_score"]))
    return {"patterns": pats, "candles": detect_candles(bars, atr),
            "pivots_used": len(piv), "atr": round(atr, 4)}
