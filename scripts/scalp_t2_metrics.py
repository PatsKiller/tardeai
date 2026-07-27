#!/usr/bin/env python3
"""M3 Moomoo/T2 — Tier-2 (order-book / depth) microstructure metrics (design §5.1).

PURE functions over an order-book snapshot. No I/O, no DB, no order/proposal path. These are the T2
metrics that only real depth (moomoo OpenD L2, e.g. NASDAQ TotalView) can supply — hidden/venue
caveats apply (displayed size understates true size; §5.2), so depth may only ever SIZE DOWN, never
justify sizing up. Same sign convention as the T0 bar_pressure / T1 TFI so downstream code takes one
input regardless of tier.

A book is bids/asks = [(price, size), …] sorted best-first.
"""
from __future__ import annotations

from typing import Optional, Sequence

Level = Sequence          # (price, size)


def _sum_size(levels: Sequence, n: int) -> float:
    return float(sum(float(s) for _p, s in list(levels)[:n]))


def book_imbalance(bids: Sequence, asks: Sequence, levels: int = 5) -> Optional[float]:
    """BI = (Σ bid_size_topN − Σ ask_size_topN) / (Σ bid_size + Σ ask_size) ∈ [−1, +1].
    +1 = all size on the bid (buy pressure). None if the book is empty."""
    b = _sum_size(bids, levels)
    a = _sum_size(asks, levels)
    if b + a <= 0:
        return None
    return (b - a) / (b + a)


def best_bid_ask(bids: Sequence, asks: Sequence) -> tuple[Optional[float], Optional[float]]:
    bb = float(bids[0][0]) if bids else None
    ba = float(asks[0][0]) if asks else None
    return bb, ba


def quoted_spread_bps(best_bid: Optional[float], best_ask: Optional[float]) -> Optional[float]:
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2.0
    if mid <= 0 or best_ask < best_bid:
        return None
    return 1e4 * (best_ask - best_bid) / mid


def microprice(best_bid: float, best_ask: float, bid_size: float, ask_size: float) -> Optional[float]:
    """Stoikov size-weighted micro-price: leans toward the side with LESS size (the side likely to
    move). = (ask·bid_size + bid·ask_size)/(bid_size+ask_size)."""
    denom = float(bid_size) + float(ask_size)
    if denom <= 0:
        return None
    return (float(best_ask) * float(bid_size) + float(best_bid) * float(ask_size)) / denom


def depth_within(bids: Sequence, asks: Sequence, mid: float, pct: float = 0.005) -> tuple[float, float]:
    """Total (bid_size, ask_size) resting within `pct` of the mid — for the size-DOWN participation
    check (never a size-up justification, §5.2)."""
    lo, hi = mid * (1 - pct), mid * (1 + pct)
    b = sum(float(s) for p, s in bids if float(p) >= lo)
    a = sum(float(s) for p, s in asks if float(p) <= hi)
    return b, a


def book_summary(bids: Sequence, asks: Sequence, levels: int = 5) -> dict:
    bb, ba = best_bid_ask(bids, asks)
    mid = ((bb + ba) / 2.0) if (bb is not None and ba is not None) else None
    bsz = float(bids[0][1]) if bids else 0.0
    asz = float(asks[0][1]) if asks else 0.0
    return {
        "best_bid": bb, "best_ask": ba, "mid": mid,
        "book_imbalance": book_imbalance(bids, asks, levels),
        "quoted_spread_bps": quoted_spread_bps(bb, ba),
        "microprice": microprice(bb, ba, bsz, asz) if (bb is not None and ba is not None) else None,
        "top_bid_size": bsz, "top_ask_size": asz,
        "levels": min(len(bids), len(asks)),
    }
