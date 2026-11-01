"""Re-entry Stage 1 / Stage 2 for a stopped-out symbol (design home/v005, SPEC section 2).

Operator 2026-11-01: "Do we really want it back above the 20-day level? Or we just want second green candle to break...
We want to catch the ride going back up." Stage 1 catches the turn; the 20-day test moves to Stage 2 as confirmation.

Stage 1 ("early setup"), all five:
  follow_through    after the swing low (lowest low since the exit), a higher low holds, then two consecutive green
                    closes, the second closing above the first green bar's high
  volume            the second green day's volume >= ``volume_ratio_min`` x its ``volume_avg_sessions`` average
  group_no_new_low  the look-through-weighted group ratio vs the benchmark made no new low in the last
                    ``group_rs_sessions`` (its lowest point of the window before them is not undercut)
  hedging_easing    index put/call vs median at least ``hedging_ease_pct`` below its peak of the last
                    ``hedging_peak_sessions`` sessions (needs that much history; fewer sessions = not met, said so)
  tier_ok           market tier not in ``blocked_tiers``
Invalidation level = the swing low FROZEN at the bar where the setup completed: any later close below it cancels the
setup, and the count restarts from that bar with a new swing low; the "Invalidated" badge shows for
``invalidation_sessions`` sessions after that close.
Stage 2 ("confirmed"), any one: a close above a ``confirm_ma_sessions`` average, or above the exit price. With fewer
bars since the swing low than the average needs (a recent IPO), the anchored VWAP from the swing low stands in.

Verdict, first match: Invalidated · Confirmed · Early setup · Basing · Still falling (thresholds under
``reentry_watch.verdict``). Every threshold comes from ``config/market_risk_policy.yaml`` ``reentry_watch``; the
defaults below only apply when a key is absent. MBI_BEHAVIOR = 0: signal and status only — no size, no order, no price
to pay. Prices shown are market facts (exit fill, closes, the swing low), never an instruction.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from scripts.lib.market_risk import contract as c

VERDICTS = ("Invalidated", "Confirmed", "Early setup", "Basing", "Still falling")
#: the Stage 1 conditions, in card order (the card shows "k of len(STAGE1_KEYS)")
STAGE1_KEYS = ("follow_through", "volume", "group_no_new_low", "hedging_easing", "tier_ok")


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _cfg(policy: dict[str, Any]) -> dict[str, Any]:
    rw = (policy or {}).get("reentry_watch") or {}
    s1 = rw.get("stage1") or {}
    s2 = rw.get("stage2") or {}
    v = rw.get("verdict") or {}
    return {
        "volume_ratio_min": float(s1.get("volume_ratio_min", 1.0)),
        "volume_avg_sessions": int(s1.get("volume_avg_sessions", 20)),
        "group_rs_sessions": int(s1.get("group_rs_sessions", 5)),
        "hedging_peak_sessions": int(s1.get("hedging_peak_sessions", 5)),
        "hedging_ease_pct": float(s1.get("hedging_ease_pct", 10.0)),
        "blocked_tiers": [str(t).upper() for t in (s1.get("blocked_tiers") or ["ORANGE", "RED"])],
        "confirm_ma_sessions": [int(x) for x in (s2.get("confirm_ma_sessions") or [10, 20])],
        "confirm_above_exit": bool(s2.get("confirm_above_exit", True)),
        "short_history_anchor": str(rw.get("short_history_anchor") or "swing_low_vwap"),
        "basing_min_sessions": int(v.get("basing_min_sessions", 3)),
        "basing_band_pct": float(v.get("basing_band_pct", 3.0)),
        "invalidation_sessions": int(v.get("invalidation_sessions", 10)),
        "trend_sessions": int(v.get("trend_sessions", 5)),
        "trend_band_pct": float(v.get("trend_band_pct", 1.0)),
    }


def _green(b: dict[str, Any]) -> bool:
    o, cl = _f(b.get("open")), _f(b.get("close"))
    return o is not None and cl is not None and cl > o


def _low(b: dict[str, Any]) -> float:
    lo = _f(b.get("low"))
    return lo if lo is not None else float(b["close"])


def find_setup(bars: list[dict[str, Any]], start: int = 0) -> dict[str, Any] | None:
    """The first completed follow-through at or after ``start``: two consecutive green closes, the second closing above
    the first green bar's high, after a swing low (the lowest low from ``start`` up to the setup) that the bars since
    have not undercut (a higher low). Returns ``{index, swing_low, low_index}`` — the swing low FROZEN at that bar."""
    for i in range(start + 1, len(bars)):
        a, b = bars[i - 1], bars[i]
        hi_a = _f(a.get("high"))
        if not (_green(a) and _green(b)):
            continue
        if float(b["close"]) <= (hi_a if hi_a is not None else float(a["close"])):
            continue
        lows = [_low(x) for x in bars[start : i + 1]]
        li = start + min(range(len(lows)), key=lambda k: lows[k])
        if li >= i - 1:
            continue  # the green bars themselves are the low: no higher low yet
        sl = _low(bars[li])
        if all(_low(x) > sl for x in bars[li + 1 : i + 1]):
            return {"index": i, "swing_low": sl, "low_index": li}
    return None


def weighted_group_ratio(
    group_closes: dict[str, list[float]], weights: dict[str, float], bench: list[float]
) -> list[float]:
    """Look-through-weighted group/benchmark ratio, each group normalised to its first close. Aligned on the tail."""
    keys = [k for k, w in weights.items() if w and group_closes.get(k)]
    if not keys or not bench:
        return []
    n = min([len(bench)] + [len(group_closes[k]) for k in keys])
    if n < 2:
        return []
    tot = sum(weights[k] for k in keys)
    out = []
    b0 = bench[-n]
    for i in range(-n, 0):
        g = sum(weights[k] / tot * (group_closes[k][i] / group_closes[k][-n]) for k in keys)
        out.append(g / (bench[i] / b0))
    return out


def group_no_new_low(ratio: list[float], sessions: int) -> bool | None:
    """None when there is not enough history to say; True when the last ``sessions`` made no new low."""
    if len(ratio) < sessions + 2:
        return None
    return min(ratio[-sessions:]) > min(ratio[: -sessions])


def hedging_easing(series: list[float], peak_sessions: int, ease_pct: float) -> tuple[bool, str]:
    """``series``: per-session index put/call-vs-median factor, newest last."""
    s = [x for x in series if x is not None]
    if len(s) < peak_sessions:
        return False, f"hedging easing (history {len(s)} of {peak_sessions} sessions)"
    peak = max(s[-peak_sessions:])
    ok = s[-1] <= peak * (1 - ease_pct / 100.0) and s[-1] < peak
    return ok, "hedging easing"


def anchored_vwap(bars: list[dict[str, Any]]) -> float | None:
    num = den = 0.0
    for b in bars:
        h, lo, cl, v = _f(b.get("high")), _f(b.get("low")), _f(b.get("close")), _f(b.get("volume"))
        if cl is None or not v:
            continue
        tp = ((h if h is not None else cl) + (lo if lo is not None else cl) + cl) / 3.0
        num += tp * v
        den += v
    return round(num / den, 4) if den else None


def evaluate(
    *,
    symbol: str,
    exit_date: str,
    exit_price: float | None,
    bars: list[dict[str, Any]],
    group_ratio: list[float],
    hedging_series: list[float],
    market_tier: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Stage 1 / Stage 2 status for one exit. ``bars``: daily OHLCV for the symbol, oldest first, through the last
    completed session (the engine's reader)."""
    k = _cfg(policy)
    bars = [b for b in bars if _f(b.get("close")) is not None]
    closes = [float(b["close"]) for b in bars]
    since = [b for b in bars if str(b.get("date") or "")[:10] >= exit_date]
    last = closes[-1] if closes else None
    out: dict[str, Any] = {
        "symbol": symbol,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "last_close": last,
        "last_date": str(bars[-1]["date"])[:10] if bars else None,
    }
    if not since or last is None:
        out.update(verdict="Still falling", stage1={"met": 0, "of": len(STAGE1_KEYS), "conditions": []},
                   stage2={"met": False, "conditions": []}, note="no session since the exit")
        c.assert_no_behavior_fields(out)
        return out

    # Walk the setups since the exit. A setup freezes its swing low; ANY later close below it cancels the setup and the
    # count restarts from that bar. ``invalidation_sessions`` only decides how long the "Invalidated" badge shows
    # (review of PR 2447, B1 round 2).
    start, active, last_invalidation = 0, None, None
    while True:
        st = find_setup(since, start)
        if st is None:
            break
        i, frozen = st["index"], st["swing_low"]
        inv = next((j for j in range(i + 1, len(since)) if float(since[j]["close"]) < frozen), None)
        if inv is None:
            active = st
            break
        last_invalidation = {"at": inv, "level": frozen, "date": str(since[inv].get("date"))[:10]}
        start = inv
    window = since[start:]
    wl = [_low(b) for b in window]
    wli = min(range(len(wl)), key=lambda x: wl[x])
    swing_low = round(active["swing_low"] if active else wl[wli], 4)

    conds = [{"key": "follow_through", "met": active is not None, "text": "higher low + 2 green closes"}]
    vol_ok = False
    if active is not None:
        j = bars.index(since[active["index"]])
        vols = [_f(b.get("volume")) for b in bars[max(0, j - k["volume_avg_sessions"]) : j]]
        vols = [v for v in vols if v]
        v2 = _f(bars[j].get("volume"))
        vol_ok = bool(vols and v2 and v2 >= k["volume_ratio_min"] * mean(vols))
    conds.append({"key": "volume", "met": vol_ok, "text": f"volume ≥{k['volume_ratio_min']:g}×"})
    g = group_no_new_low(group_ratio, k["group_rs_sessions"])
    conds.append(
        {
            "key": "group_no_new_low",
            "met": bool(g),
            "text": "look-through groups still at relative lows" if g is not None else "look-through groups not measured",
        }
    )
    h_ok, h_txt = hedging_easing(hedging_series, k["hedging_peak_sessions"], k["hedging_ease_pct"])
    conds.append({"key": "hedging_easing", "met": h_ok, "text": h_txt})
    tier_ok = str(market_tier).upper() not in k["blocked_tiers"]
    conds.append({"key": "tier_ok", "met": tier_ok, "text": f"market tier {str(market_tier).upper()}"})
    s1_met = sum(1 for x in conds if x["met"])

    # Stage 2: a moving average, or the anchored VWAP when history is short
    s2 = []
    smas: dict[str, float | None] = {}
    for n in k["confirm_ma_sessions"]:
        sma = round(mean(closes[-n:]), 4) if len(closes) >= n else None
        smas[f"sma{n}"] = sma
        if sma is not None:
            s2.append({"key": f"above_sma{n}", "met": last > sma, "text": f"close above the {n}-day {sma:.2f}"})
    avwap = None
    if any(v is None for v in smas.values()) and k["short_history_anchor"] == "swing_low_vwap":
        avwap = anchored_vwap(window[wli:] if not active else since[active["low_index"] :])
        if avwap is not None:
            s2.append({"key": "above_anchored_vwap", "met": last > avwap, "text": f"close above anchored VWAP {avwap:.2f}"})
    if k["confirm_above_exit"] and exit_price:
        s2.append({"key": "above_exit", "met": last > float(exit_price), "text": f"close above {float(exit_price):.2f}"})
    s2_met = any(x["met"] for x in s2)

    # verdict
    invalidated = (
        active is None
        and last_invalidation is not None
        and len(since) - 1 - last_invalidation["at"] < k["invalidation_sessions"]
    )
    after = window[wli + 1 :]
    recent_low = wli >= len(window) - k["basing_min_sessions"]
    band = wl[wli] * (1 + k["basing_band_pct"] / 100.0)
    basing = (not recent_low) and len(after) >= k["basing_min_sessions"] and all(
        float(b["close"]) <= band for b in after[-k["basing_min_sessions"] :]
    )
    if invalidated:
        verdict = "Invalidated"
    elif s2_met:
        verdict = "Confirmed"
    elif s1_met == len(conds):
        verdict = "Early setup"
    elif basing:
        verdict = "Basing"
    else:
        verdict = "Still falling"
    tn, tb = k["trend_sessions"], k["trend_band_pct"] / 100.0
    trend = None
    if len(closes) > tn:
        d = closes[-1] / closes[-1 - tn] - 1
        trend = "up" if d > tb else "down" if d < -tb else "flat"
    sma20 = smas.get("sma20")
    out.update(
        swing_low=swing_low,
        invalidation_level=swing_low,
        invalidated=last_invalidation if invalidated else None,
        **smas,
        anchored_vwap=avwap,
        pct_vs_exit=round((last / float(exit_price) - 1) * 100, 2) if exit_price else None,
        pct_vs_sma20=round((last / sma20 - 1) * 100, 2) if sma20 else None,
        trend=trend,
        verdict=verdict,
        stage1={"met": s1_met, "of": len(conds), "conditions": conds},
        stage2={"met": s2_met, "conditions": s2},
    )
    c.assert_no_behavior_fields(out)
    return out
