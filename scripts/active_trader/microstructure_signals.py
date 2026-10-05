"""Entry and exit microstructure signals for momentum scalps (operator-approved 2026-10-05).

Pure functions over recorder snapshots (moomoo book + tape, see microstructure_recorder), minute
bars and, when present, Schwab NASDAQ_BOOK rows. No I/O, no broker, no LLM. Every signal returns
{"on": bool | None, "value": ..., "threshold": ...}; None means "not enough data" and is never
treated as a pass or a fail.

Why: on 2026-10-05 the operator bought XNDU at 10:07:09 after a heads-up and "the supply wasn't
there". Between the 10:05 and 10:10 decisions both sides of the moomoo book were pulled ~75%
(bid 45,658 → 10,329 sh, ask 35,217 → 10,779 sh) and minute volume fell from 4,503 to 1,000 sh
right as the order went in. These signals make that visible while it happens.

Snapshot shape (recorder line): {"t": epoch, "b": [[price, size]...], "a": [[price, size]...],
"l": last, "k": [[epoch, price, volume, "B"|"S"|"N"], ...new prints since the previous line]}.
Bar shape: {"t": iso or epoch, "o","h","l","c","v", optional "vw"} oldest→newest, completed bars.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from statistics import median
from typing import Any, Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class SignalConfig:
    """Defaults are v1 priors. A `microstructure_signals:` section in
    config/scalp_signal_engine.yaml overrides any field (operator-ratified changes only);
    signal_calibration.py proposes changes, it never writes them."""
    window_s: float = 60.0              # look-back for book trends
    near_pct: float = 1.0               # "near the inside ask" = within this % above it
    thin_ratio: float = 0.6             # inside/near ask size now ÷ then ≤ this → supply thinning
    refill_mult: float = 2.0            # bought at an unchanged ask ≥ this × the starting ask size → hidden seller
    pull_pct: float = 50.0              # both sides' depth fell ≥ this % → book pulled
    accel_mult: float = 2.0             # last 1-min volume ÷ prior-5 average ≥ this → volume acceleration
    accel_lookback: int = 5
    extended_vwap_pct: float = 3.0      # above session VWAP by more than this → extended
    tape_prints: int = 50
    tape_flip_ratio: float = 0.45       # buy share of the last prints below this → tape flipped to sellers
    climax_mult: float = 3.0            # bar volume ≥ this × prior average …
    climax_lookback: int = 10
    climax_wick_frac: float = 0.5       # … with an upper wick ≥ this share of the bar's range
    wall_x_median: float = 4.0          # an ask level ≥ this × the median ask size is a wall
    schwab_mm_stack: int = 4            # ≥ this many market makers at the Schwab inside ask

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "SignalConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (raw or {}).items() if k in known})


def _sig(on: Optional[bool], value: Any = None, threshold: Any = None, **extra) -> dict:
    out = {"on": on, "value": value, "threshold": threshold}
    out.update(extra)
    return out


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _epoch(t: Any) -> Optional[float]:
    if isinstance(t, (int, float)):
        return float(t)
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ── book helpers ─────────────────────────────────────────────────────────────

def _levels(snap: Mapping[str, Any], side: str) -> list[tuple[float, float]]:
    out = []
    for lv in snap.get(side) or []:
        p, s = (_num(lv[0]), _num(lv[1])) if isinstance(lv, (list, tuple)) else (_num(lv.get("price")), _num(lv.get("size")))
        if p is not None and s is not None:
            out.append((p, s))
    return out


def book_stats(snap: Mapping[str, Any], *, near_pct: float) -> Optional[dict]:
    bids, asks = _levels(snap, "b"), _levels(snap, "a")
    if not bids or not asks:
        return None
    best_ask = asks[0][0]
    near = sum(s for p, s in asks if p <= best_ask * (1 + near_pct / 100.0))
    return {"best_bid": bids[0][0], "best_ask": best_ask, "ask_inside": asks[0][1], "bid_inside": bids[0][1],
            "ask_near": near, "bid_depth": sum(s for _, s in bids), "ask_depth": sum(s for _, s in asks),
            "spread_bps": ((best_ask - bids[0][0]) / ((best_ask + bids[0][0]) / 2) * 1e4) if best_ask + bids[0][0] > 0 else None}


def _window(snaps: Sequence[Mapping[str, Any]], now: float, window_s: float) -> list[Mapping[str, Any]]:
    return [s for s in snaps if (_num(s.get("t")) or 0) <= now and (_num(s.get("t")) or 0) >= now - window_s]


def ticks(snaps: Iterable[Mapping[str, Any]]) -> list[tuple[float, float, float, str]]:
    out = []
    for s in snaps:
        for k in s.get("k") or []:
            try:
                out.append((float(k[0]), float(k[1]), float(k[2]), str(k[3])))
            except (TypeError, ValueError, IndexError):
                continue
    out.sort(key=lambda x: x[0])
    return out


def bars_from_ticks(tk: Sequence[tuple[float, float, float, str]]) -> list[dict]:
    """1-min bars built from recorded prints (consolidated moomoo tape, not IEX). A bar is only as
    complete as the recorder's coverage of that minute."""
    bars: dict[int, dict] = {}
    for t, p, v, _ in tk:
        m = int(t // 60) * 60
        b = bars.get(m)
        if b is None:
            bars[m] = {"t": float(m), "o": p, "h": p, "l": p, "c": p, "v": v, "pv": p * v}
        else:
            b["h"], b["l"], b["c"] = max(b["h"], p), min(b["l"], p), p
            b["v"] += v
            b["pv"] += p * v
    out = []
    for m in sorted(bars):
        b = bars[m]
        b["vw"] = b.pop("pv") / b["v"] if b["v"] else None
        out.append(b)
    return out


def session_vwap(bars: Sequence[Mapping[str, Any]]) -> Optional[float]:
    pv = vol = 0.0
    for b in bars:
        v = _num(b.get("v")) or 0.0
        px = _num(b.get("vw")) or _num(b.get("c"))
        if px is None or v <= 0:
            continue
        pv += px * v
        vol += v
    return pv / vol if vol else None


# ── entry signals ────────────────────────────────────────────────────────────

def supply_thinning(snaps, now, cfg: SignalConfig) -> dict:
    w = _window(snaps, now, cfg.window_s)
    st = [x for x in (book_stats(s, near_pct=cfg.near_pct) for s in w) if x]
    if len(st) < 2 or not st[0]["ask_near"]:
        return _sig(None, threshold=cfg.thin_ratio)
    r = st[-1]["ask_near"] / st[0]["ask_near"]
    return _sig(r <= cfg.thin_ratio, round(r, 3), cfg.thin_ratio, ask_near_then=st[0]["ask_near"], ask_near_now=st[-1]["ask_near"])


def ask_refill(snaps, now, cfg: SignalConfig) -> dict:
    """Hidden seller: prints keep lifting the same ask price but the offer never shrinks."""
    w = _window(snaps, now, cfg.window_s)
    st = [(s, book_stats(s, near_pct=cfg.near_pct)) for s in w]
    st = [(s, b) for s, b in st if b]
    if len(st) < 2:
        return _sig(None, threshold=cfg.refill_mult)
    a0 = st[0][1]["best_ask"]
    if any(abs(b["best_ask"] - a0) > 1e-9 for _, b in st):
        return _sig(False, 0.0, cfg.refill_mult, note="ask price moved")
    lifted = sum(v for t, p, v, d in ticks(s for s, _ in st[1:]) if d == "B" and p >= a0 - 1e-9)
    start = st[0][1]["ask_inside"] or 0.0
    ratio = lifted / start if start else None
    holding = st[-1][1]["ask_inside"] >= start * 0.8
    if ratio is None:
        return _sig(None, threshold=cfg.refill_mult)
    return _sig(ratio >= cfg.refill_mult and holding, round(ratio, 2), cfg.refill_mult,
                ask_price=a0, bought_at_ask=lifted, ask_size_start=start, ask_size_now=st[-1][1]["ask_inside"])


def book_pull(snaps, now, cfg: SignalConfig) -> dict:
    w = _window(snaps, now, cfg.window_s)
    st = [x for x in (book_stats(s, near_pct=cfg.near_pct) for s in w) if x]
    if len(st) < 2 or not st[0]["bid_depth"] or not st[0]["ask_depth"]:
        return _sig(None, threshold=cfg.pull_pct)
    bd = (st[-1]["bid_depth"] / st[0]["bid_depth"] - 1) * 100
    ad = (st[-1]["ask_depth"] / st[0]["ask_depth"] - 1) * 100
    return _sig(bd <= -cfg.pull_pct and ad <= -cfg.pull_pct, {"bid_pct": round(bd, 1), "ask_pct": round(ad, 1)},
                -cfg.pull_pct)


def volume_acceleration(bars: Sequence[Mapping[str, Any]], cfg: SignalConfig) -> dict:
    n = cfg.accel_lookback
    if len(bars) < n + 1:
        return _sig(None, threshold=cfg.accel_mult)
    prior = [_num(b.get("v")) or 0.0 for b in bars[-n - 1:-1]]
    avg = sum(prior) / n
    last = _num(bars[-1].get("v")) or 0.0
    if avg <= 0:
        return _sig(None, threshold=cfg.accel_mult)
    r = last / avg
    return _sig(r >= cfg.accel_mult, round(r, 2), cfg.accel_mult, last_vol=last, prior_avg=round(avg, 1))


def high_break(bars: Sequence[Mapping[str, Any]], cfg: SignalConfig, *, premarket_high: Optional[float] = None) -> dict:
    if len(bars) < 2:
        return _sig(None)
    prior_hod = max(_num(b.get("h")) or 0.0 for b in bars[:-1])
    level = max(prior_hod, premarket_high or 0.0)
    close = _num(bars[-1].get("c"))
    accel = volume_acceleration(bars, cfg)
    if close is None:
        return _sig(None)
    return _sig(close > level and bool(accel["on"]), close, level,
                level_kind="premarket_high" if premarket_high and premarket_high >= prior_hod else "high_of_day",
                on_volume=accel["on"])


def vwap_distance(bars: Sequence[Mapping[str, Any]], last: Optional[float], cfg: SignalConfig) -> dict:
    vw = session_vwap(bars)
    if vw is None or last is None:
        return _sig(None, threshold=cfg.extended_vwap_pct)
    d = (last - vw) / vw * 100
    return _sig(d > cfg.extended_vwap_pct, round(d, 2), cfg.extended_vwap_pct, vwap=round(vw, 4))


def schwab_book(row: Optional[Mapping[str, Any]], cfg: SignalConfig) -> dict:
    """Schwab NASDAQ_BOOK adds market-maker counts per level: many MMs stacked at the inside ask
    is supply the moomoo size alone does not show."""
    if not row:
        return _sig(None, threshold=cfg.schwab_mm_stack, source="schwab", status="NO_BOOK")
    asks = row.get("ask_levels") or []
    bids = row.get("bid_levels") or []
    a0 = asks[0] if asks else {}
    mm = a0.get("mm_count")
    return _sig((mm or 0) >= cfg.schwab_mm_stack if mm is not None else None, mm, cfg.schwab_mm_stack,
                source="schwab", ask_inside=a0.get("size"), bid_inside=(bids[0] if bids else {}).get("size"),
                bid_mm=(bids[0] if bids else {}).get("mm_count"))


def entry_signals(snaps: Sequence[Mapping[str, Any]], bars: Sequence[Mapping[str, Any]], *, now: float,
                  cfg: SignalConfig, last: Optional[float] = None, premarket_high: Optional[float] = None,
                  schwab_row: Optional[Mapping[str, Any]] = None) -> dict:
    snaps = sorted(snaps, key=lambda s: _num(s.get("t")) or 0)
    if last is None and snaps:
        last = _num(snaps[-1].get("l"))
    return {
        "supply_thinning": supply_thinning(snaps, now, cfg),
        "ask_refill": ask_refill(snaps, now, cfg),
        "book_pull": book_pull(snaps, now, cfg),
        "volume_acceleration": volume_acceleration(bars, cfg),
        "high_break": high_break(bars, cfg, premarket_high=premarket_high),
        "vwap_distance": vwap_distance(bars, last, cfg),
        "schwab_mm_stack": schwab_book(schwab_row, cfg),
    }


# ── exit signals ─────────────────────────────────────────────────────────────

def tape_flip(snaps, cfg: SignalConfig) -> dict:
    tk = ticks(snaps)[-cfg.tape_prints:]
    buy = sum(v for _, _, v, d in tk if d == "B")
    sell = sum(v for _, _, v, d in tk if d == "S")
    if buy + sell <= 0:
        return _sig(None, threshold=cfg.tape_flip_ratio)
    r = buy / (buy + sell)
    return _sig(r < cfg.tape_flip_ratio, round(r, 3), cfg.tape_flip_ratio, prints=len(tk))


def volume_climax(bars: Sequence[Mapping[str, Any]], cfg: SignalConfig) -> dict:
    n = cfg.climax_lookback
    if len(bars) < n + 1:
        return _sig(None, threshold=cfg.climax_mult)
    b = bars[-1]
    prior = [_num(x.get("v")) or 0.0 for x in bars[-n - 1:-1]]
    avg = sum(prior) / n
    h, lo, o, c, v = (_num(b.get(k)) for k in ("h", "l", "o", "c", "v"))
    if None in (h, lo, o, c, v) or avg <= 0 or h <= lo:
        return _sig(None, threshold=cfg.climax_mult)
    wick = (h - max(o, c)) / (h - lo)
    r = v / avg
    return _sig(r >= cfg.climax_mult and wick >= cfg.climax_wick_frac, round(r, 2), cfg.climax_mult,
                upper_wick_frac=round(wick, 2))


def ask_wall(snaps, now, cfg: SignalConfig) -> dict:
    """A large offer appears just above price that was not there a window ago."""
    w = _window(snaps, now, cfg.window_s)
    if len(w) < 2:
        return _sig(None, threshold=cfg.wall_x_median)

    def wall(s):
        asks = _levels(s, "a")
        if not asks:
            return None
        med = median(sz for _, sz in asks)
        best = asks[0][0]
        near = [(p, sz) for p, sz in asks if p <= best * (1 + cfg.near_pct / 100.0)]
        big = max(near, key=lambda x: x[1]) if near else None
        return (big, med) if big and med and big[1] >= cfg.wall_x_median * med else (None, med)

    then, now_ = wall(w[0]), wall(w[-1])
    if now_ is None:
        return _sig(None, threshold=cfg.wall_x_median)
    appeared = now_[0] is not None and (then is None or then[0] is None)
    return _sig(appeared, now_[0][1] if now_[0] else None, cfg.wall_x_median,
                price=now_[0][0] if now_[0] else None)


def close_below_prior_low(bars: Sequence[Mapping[str, Any]]) -> dict:
    if len(bars) < 2:
        return _sig(None)
    c, pl = _num(bars[-1].get("c")), _num(bars[-2].get("l"))
    if c is None or pl is None:
        return _sig(None)
    return _sig(c < pl, c, pl)


def vwap_loss(bars: Sequence[Mapping[str, Any]]) -> dict:
    if len(bars) < 2:
        return _sig(None)
    vw_prev, vw_now = session_vwap(bars[:-1]), session_vwap(bars)
    pc, c = _num(bars[-2].get("c")), _num(bars[-1].get("c"))
    if None in (vw_prev, vw_now, pc, c):
        return _sig(None)
    return _sig(pc >= vw_prev and c < vw_now, c, round(vw_now, 4))


def exit_signals(snaps: Sequence[Mapping[str, Any]], bars: Sequence[Mapping[str, Any]], *, now: float,
                 cfg: SignalConfig) -> dict:
    snaps = sorted(snaps, key=lambda s: _num(s.get("t")) or 0)
    return {
        "tape_flip": tape_flip(snaps, cfg),
        "volume_climax": volume_climax(bars, cfg),
        "ask_wall": ask_wall(snaps, now, cfg),
        "close_below_prior_low": close_below_prior_low(bars),
        "vwap_loss": vwap_loss(bars),
    }


def fired(signals: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return [k for k, v in (signals or {}).items() if isinstance(v, Mapping) and v.get("on") is True]
