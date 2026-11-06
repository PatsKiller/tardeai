"""Breadth proxy from public daily ETF bars (DSN-20261031-market-risk-engine §5.5, gap-close 2026-10-31).

NYSE advance/decline and new-high/new-low series have no free public API, and the ``market_breadth_daily`` store
(P1-T5) is not built. Until it is, breadth is measured over the eleven sector SPDRs, which together span the S&P 500:

* % of sector ETFs above their 20- and 50-day averages;
* % within ``near_low_pct`` of their 52-week low (new-low proxy) and of their 52-week high;
* a ratio-adjusted McClellan oscillator over the sector ETFs' daily advance/decline;
* RSP vs SPY 20-session relative change (equal weight vs cap weight).

Pure functions over closes; the caller supplies as-of-correct bars (``DataReader.daily_bars``), so nothing here can
look ahead. Fewer than ``min_members`` usable ETFs → ``None`` (the caller reports UNKNOWN, never zero).
"""

from __future__ import annotations

from typing import Any


def _sma(v: list[float], n: int) -> float | None:
    return sum(v[-n:]) / n if len(v) >= n else None


def _ema(values: list[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out: list[float] = []
    for x in values:
        out.append(x if not out else out[-1] + k * (x - out[-1]))
    return out


def _share_above(closes: dict[str, list[float]], n: int, back: int = 0) -> float | None:
    hits = tot = 0
    for c in closes.values():
        series = c[: len(c) - back] if back else c
        m = _sma(series, n)
        if m is None:
            continue
        tot += 1
        hits += series[-1] > m
    return hits / tot if tot else None


def mcclellan(closes: dict[str, list[float]]) -> list[float]:
    """Ratio-adjusted McClellan oscillator: EMA19 - EMA39 of 1000 * (adv - dec) / (adv + dec), aligned on the end."""
    n = min((len(c) for c in closes.values()), default=0)
    net: list[float] = []
    for i in range(n - 1, 0, -1):
        adv = dec = 0
        for c in closes.values():
            a, b = c[len(c) - i], c[len(c) - i - 1]
            adv += a > b
            dec += a < b
        net.append(1000.0 * (adv - dec) / (adv + dec) if adv + dec else 0.0)
    if len(net) < 40:
        return []
    e19, e39 = _ema(net, 19), _ema(net, 39)
    return [a - b for a, b in zip(e19, e39)]


def measure(
    closes: dict[str, list[float]], style: dict[str, list[float]], cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """``closes``: sector ETF -> ascending closes; ``style``: {'RSP': [...], 'SPY': [...]}. Returns the measures."""
    usable = {s: c for s, c in closes.items() if len(c) >= int(cfg["min_history_sessions"])}
    if len(usable) < int(cfg["min_members"]):
        return None
    lookback = int(cfg["high_low_sessions"])
    near = float(cfg["near_low_pct"]) / 100.0
    at_low = at_high = 0
    for c in usable.values():
        w = c[-lookback:]
        lo, hi = min(w), max(w)
        at_low += c[-1] <= lo * (1 + near)
        at_high += c[-1] >= hi * (1 - near)
    mc = mcclellan(usable)
    thrust_n = int(cfg["thrust_sessions"])
    rel = None
    r, s = style.get("RSP") or [], style.get("SPY") or []
    if len(r) > 20 and len(s) > 20:
        rel = 100.0 * ((r[-1] / s[-1]) / (r[-21] / s[-21]) - 1.0)
    return {
        "members": len(usable),
        "pct_above_20": _share_above(usable, 20),
        "pct_above_50": _share_above(usable, 50),
        "pct_above_20_then": _share_above(usable, 20, back=thrust_n),
        "pct_at_low": at_low / len(usable),
        "pct_at_high": at_high / len(usable),
        "mcclellan": mc[-1] if mc else None,
        "mcclellan_min_recent": min(mc[-thrust_n - 1 :]) if len(mc) > thrust_n else None,
        "rsp_spy_rel20": rel,
    }


def score(m: dict[str, Any], cfg: dict[str, Any]) -> tuple[float, list[str]]:
    """Deterioration points 0-100 and the phrases that earned them (weights in policy breadth.proxy.points)."""
    p = cfg["points"]
    pts = 0.0
    why: list[str] = []
    a20, a50 = m["pct_above_20"], m["pct_above_50"]
    if a20 is not None:
        pts += (1 - a20) * float(p["below_20dma_full"])
    if a50 is not None:
        pts += (1 - a50) * float(p["below_50dma_full"])
        if a50 <= float(cfg["weak_above_50"]):
            why.append(f"{round(100 * a50)}% of sectors above 50-day")
    pts += m["pct_at_low"] * float(p["at_52w_low_full"])
    if m["pct_at_low"] >= float(cfg["many_at_low"]):
        why.append(f"{round(100 * m['pct_at_low'])}% of sectors at 52-week lows")
    mc = m["mcclellan"]
    if mc is not None and mc < 0:
        pts += min(1.0, -mc / float(cfg["mcclellan_full"])) * float(p["mcclellan_negative_full"])
        if mc <= -float(cfg["mcclellan_full"]) / 2:
            why.append(f"McClellan {mc:+.0f}")
    rel = m["rsp_spy_rel20"]
    if rel is not None and rel <= float(cfg["rsp_spy_weak_pct"]):
        pts += float(p["rsp_spy_weak"])
        why.append(f"RSP vs SPY {rel:+.1f}% in 20d")
    return round(min(100.0, pts), 1), why


def improving(m: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    """A breadth thrust: participation jumped from washed-out to broad, or the McClellan swung from deeply negative
    to positive, inside ``thrust_sessions``. Returns the phrase, or None."""
    imp = cfg["improving"]
    a20, then = m["pct_above_20"], m["pct_above_20_then"]
    if a20 is not None and then is not None:
        if a20 >= float(imp["thrust_to"]) and a20 - then >= float(imp["thrust_rise"]):
            return f"breadth thrust: {round(100 * then)}% → {round(100 * a20)}% of sectors above 20-day"
    mc, lo = m["mcclellan"], m["mcclellan_min_recent"]
    if (
        mc is not None
        and lo is not None
        and lo <= -float(imp["mcclellan_swing"])
        and mc >= float(imp["mcclellan_swing"])
    ):
        return f"McClellan swing {lo:+.0f} → {mc:+.0f}"
    return None
