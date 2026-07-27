"""Stage 5 — deterministic market-data features (computed OUTSIDE callbacks).

Versioned, no lookahead, no LLM, no authority, null when input absent, and
byte-for-byte deterministic on replay. Does NOT implement RES/RRS or any trade
decision (those belong to later stages).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

FEATURE_VERSION = "moomoo-features-1"


def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


@dataclass
class BookLevel:
    price: float
    size: float


def spread_cents(bid: Optional[float], ask: Optional[float]):
    if bid is None or ask is None:
        return None
    return round((ask - bid) * 100, 4)


def spread_bps(bid: Optional[float], ask: Optional[float]):
    mid = midprice(bid, ask)
    if mid is None or mid == 0:
        return None
    return round((ask - bid) / mid * 10000, 4)


def midprice(bid: Optional[float], ask: Optional[float]):
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2


def microprice(bid: float, ask: float, bid_size: float, ask_size: float):
    denom = bid_size + ask_size
    if bid is None or ask is None or denom is None or denom == 0:
        return None
    return (ask * bid_size + bid * ask_size) / denom


def weighted_mid(bid, ask, bid_size, ask_size):
    return microprice(bid, ask, bid_size, ask_size)


def top_imbalance(bid_size: Optional[float], ask_size: Optional[float]):
    denom = None if bid_size is None or ask_size is None else bid_size + ask_size
    return _safe_div((bid_size - ask_size) if denom else None, denom)


def level_weighted_imbalance(bids: list[BookLevel], asks: list[BookLevel],
                             decay: float = 0.5):
    if not bids or not asks:
        return None
    num = den = 0.0
    for lvl, (b, a) in enumerate(zip(bids, asks)):
        w = decay ** lvl
        tot = b.size + a.size
        if tot <= 0:
            continue
        num += w * (b.size - a.size) / tot
        den += w
    return None if den == 0 else num / den


def depth_by_level(levels: list[BookLevel]) -> list[float]:
    return [lvl.size for lvl in levels]


@dataclass
class FeatureSnapshot:
    symbol: str
    as_of_monotonic_ns: int
    feature_version: str
    last: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    spread_cents: Optional[float]
    spread_bps: Optional[float]
    top_bid_size: Optional[float]
    top_ask_size: Optional[float]
    top_imbalance: Optional[float]
    lw_imbalance: Optional[float]
    microprice: Optional[float]
    weighted_mid: Optional[float]
    vwap: Optional[float]
    rvol: Optional[float]
    roc: Optional[float]
    session_high: Optional[float]
    session_low: Optional[float]
    data_age_ms: Optional[float]
    gap_state: str
    input_refs: dict

    def as_dict(self):
        return asdict(self)


def compute_snapshot(*, symbol: str, as_of_ns: int, last=None, bid=None, ask=None,
                     bid_size=None, ask_size=None, bids: list[BookLevel] | None = None,
                     asks: list[BookLevel] | None = None, vwap=None, rvol=None, roc=None,
                     session_high=None, session_low=None, last_event_ns=None,
                     gap_state: str = "HEALTHY", input_refs: dict | None = None) -> FeatureSnapshot:
    mid = midprice(bid, ask)
    data_age = None if last_event_ns is None else round((as_of_ns - last_event_ns) / 1e6, 3)
    return FeatureSnapshot(
        symbol=symbol, as_of_monotonic_ns=as_of_ns, feature_version=FEATURE_VERSION,
        last=last, bid=bid, ask=ask, mid=mid,
        spread_cents=spread_cents(bid, ask), spread_bps=spread_bps(bid, ask),
        top_bid_size=bid_size, top_ask_size=ask_size,
        top_imbalance=top_imbalance(bid_size, ask_size),
        lw_imbalance=level_weighted_imbalance(bids or [], asks or []),
        microprice=(microprice(bid, ask, bid_size, ask_size)
                    if None not in (bid, ask, bid_size, ask_size) else None),
        weighted_mid=(weighted_mid(bid, ask, bid_size, ask_size)
                      if None not in (bid, ask, bid_size, ask_size) else None),
        vwap=vwap, rvol=rvol, roc=roc, session_high=session_high, session_low=session_low,
        data_age_ms=data_age, gap_state=gap_state, input_refs=input_refs or {})
