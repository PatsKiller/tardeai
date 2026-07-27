#!/usr/bin/env python3
"""M3-S6 — Tier-1 (trades + NBBO) microstructure metric library (design §4.3 T1 formulas).

PURE functions over consolidated trades + NBBO quotes. No I/O, no DB, no order/proposal path. These
are the T1 substitutes on the fallback ladder — they REQUIRE real-time CONSOLIDATED (SIP) data. They
are fixture-testable here, but the runner (scalp_t1_gate.py) makes it structurally impossible to feed
them IEX-only / delayed / unentitled data (which would be a ~2-3% venue sample, weaker than the T0
BarPressure fallback — the exact failure M3-S5.5 warned against).

Metrics:
  - lee_ready_sign        — Lee & Ready (1991) trade-side classification (print vs contemporaneous mid,
                            tick-test at mid). +1 buy-initiated, -1 sell-initiated, 0 indeterminate.
  - trade_flow_imbalance  — TFI = (V_buy - V_sell)/(V_buy + V_sell) over a window ∈ [-1, +1].
  - effective_spread_bps  — volume-weighted 10^4 · 2·|P - mid|/mid.
  - kyle_lambda           — price-impact slope of ΔP on signed dollar volume (Kyle 1985).
  - vpin                  — Easley/López de Prado/O'Hara order-flow toxicity over equal-volume buckets.

A "trade" is {price, size, ts}; a "quote" is {bid, ask, ts}. Same sign convention as the T0
bar_pressure / T2 book-imbalance so downstream gate code takes one input regardless of tier.
"""
from __future__ import annotations

import statistics
from typing import Mapping, Optional, Sequence


def _mid(q: Mapping) -> Optional[float]:
    b, a = q.get("bid"), q.get("ask")
    if b is None or a is None:
        return None
    return (float(b) + float(a)) / 2.0


def quote_at(quotes: Sequence[Mapping], ts) -> Optional[Mapping]:
    """The prevailing quote at or before `ts` (contemporaneous — no lag). Quotes assumed sorted by ts."""
    prevailing = None
    for q in quotes:
        if q.get("ts") is not None and ts is not None and q["ts"] <= ts:
            prevailing = q
        else:
            break
    return prevailing if prevailing is not None else (quotes[0] if quotes else None)


def lee_ready_sign(price: float, mid: Optional[float], last_diff_price: Optional[float] = None) -> int:
    """+1 buy-initiated (print above mid), -1 sell-initiated (below mid); at mid → tick test against
    the last differing trade price. 0 if indeterminate. Contemporaneous quotes (no 1990s 5s lag)."""
    if mid is None:
        return 0
    if price > mid:
        return 1
    if price < mid:
        return -1
    # at mid → tick test
    if last_diff_price is None:
        return 0
    if price > last_diff_price:
        return 1
    if price < last_diff_price:
        return -1
    return 0


def sign_trades(trades: Sequence[Mapping], quotes: Sequence[Mapping]) -> list[dict]:
    """Attach a Lee-Ready side to each trade using the contemporaneous mid + tick test. Pure."""
    out = []
    last_diff = None
    for t in trades:
        p = float(t["price"])
        q = quote_at(quotes, t.get("ts"))
        s = lee_ready_sign(p, _mid(q) if q else None, last_diff)
        out.append({"price": p, "size": float(t["size"]), "ts": t.get("ts"), "side": s})
        if last_diff is None or p != last_diff:
            last_diff = p
    return out


def trade_flow_imbalance(signed: Sequence[Mapping]) -> Optional[float]:
    """TFI = (V_buy - V_sell)/(V_buy + V_sell) ∈ [-1,1]. None if no signed volume."""
    vb = sum(t["size"] for t in signed if t["side"] > 0)
    vs = sum(t["size"] for t in signed if t["side"] < 0)
    tot = vb + vs
    if tot <= 0:
        return None
    return (vb - vs) / tot


def effective_spread_bps(signed_or_trades: Sequence[Mapping], quotes: Sequence[Mapping]) -> Optional[float]:
    """Volume-weighted effective spread in bps: 10^4 · 2·|P - mid|/mid. None if unmeasurable."""
    num = den = 0.0
    for t in signed_or_trades:
        q = quote_at(quotes, t.get("ts"))
        m = _mid(q) if q else None
        if m and m > 0:
            es = 1e4 * 2.0 * abs(float(t["price"]) - m) / m
            num += es * float(t["size"]); den += float(t["size"])
    return (num / den) if den > 0 else None


def kyle_lambda(bars: Sequence[Mapping]) -> Optional[float]:
    """Kyle's λ: OLS slope of ΔP on signed dollar volume across bars. Each bar needs {close, signed_dollar_vol}
    (signed_dollar_vol = side · price · volume aggregated in the bar). λ ≈ price move per unit signed $."""
    xs, ys = [], []
    prev = None
    for b in bars:
        c = b.get("close"); sdv = b.get("signed_dollar_vol")
        if c is None:
            continue
        if prev is not None and sdv is not None:
            xs.append(float(sdv)); ys.append(float(c) - prev)
        prev = float(c)
    n = len(xs)
    if n < 2:
        return None
    mx = statistics.mean(xs); my = statistics.mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return None
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return cov / var


def vpin(signed: Sequence[Mapping], bucket_volume: float, n_buckets: Optional[int] = None) -> Optional[float]:
    """VPIN over equal-VOLUME buckets: split signed trades into buckets of `bucket_volume`, and
    VPIN = mean_over_buckets |V_buy - V_sell| / bucket_volume. Uses the last `n_buckets` if given."""
    if bucket_volume <= 0:
        return None
    buckets: list[dict] = []
    cur = {"buy": 0.0, "sell": 0.0, "vol": 0.0}
    for t in signed:
        remaining = float(t["size"])
        side = t["side"]
        while remaining > 0:
            room = bucket_volume - cur["vol"]
            take = min(remaining, room)
            if side > 0:
                cur["buy"] += take
            elif side < 0:
                cur["sell"] += take
            cur["vol"] += take; remaining -= take
            if cur["vol"] >= bucket_volume - 1e-9:
                buckets.append(cur); cur = {"buy": 0.0, "sell": 0.0, "vol": 0.0}
    if not buckets:
        return None
    use = buckets[-n_buckets:] if n_buckets else buckets
    return statistics.mean(abs(bk["buy"] - bk["sell"]) / bucket_volume for bk in use)
